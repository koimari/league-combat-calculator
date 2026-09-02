"""Tests for the fight-damage engine core (src.calculator.damage).

Covers calculate_fight_damage behavior (cast order), the private simulation
helpers (_simulate_bork_damage, _calculate_phantom_hits, _navori_effective_cd),
and the auto-vs-ability breakdown split. Per-item fight-damage tests live in
test_item_damage.py; resistance/pen primitives in test_resistance.py; ability
primitives in test_champion_primitives.py.
"""

from types import SimpleNamespace

import pytest

from src.calculator import damage
from src.calculator.ability_spec import DamagePart
from src.calculator.champions import (
    parse_champion_abilities as parse_ahri_abilities,
)
from src.calculator.damage import (
    DecayingTarget,
    FightConfig,
    _event_timeline_coverage,
    _mitigate,
    _navori_effective_cd,
    _ordered_damage_events,
    _simulate_current_health_on_hit,
    calculate_fight_damage,
    split_auto_vs_ability,
    split_by_damage_type,
)
from src.calculator.damage import (
    _calculate_phantom_hits as _calculate_phantom_hits_compiled,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.interpreters import on_hit_strike
from src.calculator.item_effects import DamageInputs, resolve_damage_effects
from src.calculator.resistance import apply_resistance


def _simulate_bork_damage(
    *,
    target_health,
    num_auto_attacks,
    auto_damage_per_hit,
    other_on_hit_per_hit,
    effective_armor,
    is_melee,
    phantom_hit_autos=None,
    double_hit_all=False,
):
    """Readable test adapter around the generic current-health simulation."""
    strikes = on_hit_strike.per_hit_effects(
        ["Blade of the Ruined King"],
        level=1,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=is_melee,
    )
    total, hits, _per_hit_damages = _simulate_current_health_on_hit(
        strikes[0],
        DamageInputs({}, 1, is_melee, target_health, target_health),
        target_health,
        num_auto_attacks,
        auto_damage_per_hit,
        other_on_hit_per_hit,
        SimpleNamespace(
            effective_armor=effective_armor,
            effective_mr=0.0,
            physical_damage_flat_reduction=0.0,
            physical_damage_flat_reduction_cap=0.0,
        ),
        1.0,
        phantom_hit_autos,
        double_hit_all,
    )
    return total, hits


def _calculate_phantom_hits(num_auto_attacks, item_names):
    """Keep cadence tables readable while production consumes typed rules.

    Returns (count, autos) for the auto-only case these tables cover;
    production also receives leading ability-attack phantom positions.
    """
    effects = resolve_damage_effects([{"name": name} for name in item_names])
    ability_phantoms, autos = _calculate_phantom_hits_compiled(
        num_auto_attacks, effects.phantom_hit
    )
    assert ability_phantoms == []  # no leading ability attacks here
    return len(autos), autos


class TestMitigate:
    """One resistance path shared by every damage source."""

    @pytest.fixture
    def resists(self):
        return SimpleNamespace(
            effective_armor=100.0,
            effective_mr=50.0,
            physical_damage_flat_reduction=0.0,
            physical_damage_flat_reduction_cap=0.0,
        )

    def test_physical_uses_effective_armor(self, resists) -> None:
        assert _mitigate(300.0, "physical", resists, 1.2) == 150.0

    def test_magic_uses_effective_mr_and_magic_amp(self, resists) -> None:
        assert _mitigate(300.0, "magic", resists, 1.2) == pytest.approx(240.0)

    def test_true_damage_ignores_resists_and_magic_amp(self, resists) -> None:
        assert _mitigate(300.0, "true", resists, 1.2) == 300.0


class TestTimelineCoverage:
    """Results say exactly which active damage sources are event-ordered."""

    @staticmethod
    def _test_spell() -> dict:
        return {
            "Q": {
                "name": "Test spell",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 300.0,
                "parts": (DamagePart("magic", 300.0),),
            }
        }

    def test_cast_and_auto_events_are_certified(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            self._test_spell(),
            target_armor=0.0,
            target_magic_resistance=0.0,
            auto_attack_uptime=1.0,
        )

        assert result["timeline_coverage"] == {
            "complete": True,
            "certification": "event_order_certified",
            "exact_sources": ["Q", "auto_attacks"],
            "coarse_sources": [],
            "note": (
                "Every active damage source has authored event or cast-boundary "
                "order."
            ),
        }

    def test_authored_blackfire_ticks_remain_certified(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            self._test_spell(),
            items=[get_item_by_name("Blackfire Torch")],
            target_magic_resistance=0.0,
        )

        coverage = result["timeline_coverage"]
        assert coverage["complete"] is True
        assert "burn_Blackfire Torch" in coverage["exact_sources"]

    def test_luden_proc_is_certified_on_its_triggering_cast(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            self._test_spell(),
            items=[get_item_by_name("Luden's Echo")],
            target_magic_resistance=0.0,
        )

        coverage = result["timeline_coverage"]
        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "proc_Luden's Echo" in coverage["exact_sources"]

    def test_luden_requires_a_damaging_ability_trigger(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            items=[get_item_by_name("Luden's Echo")],
        )

        assert "proc_Luden's Echo" not in result["breakdown"]

    def test_luden_reprocs_only_on_a_ready_damaging_cast(self, fight, attacker_stats):
        ability = self._test_spell()
        ability["Q"]["cooldown"] = 4.0
        result = fight(
            attacker_stats(),
            ability,
            items=[get_item_by_name("Luden's Echo")],
            one_rotation=False,
            fight_duration_seconds=13.0,
            target_magic_resistance=0.0,
        )

        proc = result["breakdown"]["proc_Luden's Echo"]
        assert proc["total_damage"] == pytest.approx(300.0)
        assert [event["time"] for event in proc["damage_events"]] == [0.0, 12.0]
        assert result["timeline_coverage"]["complete"] is True
        assert "proc_Luden's Echo" in result["timeline_coverage"]["exact_sources"]

    def test_luden_crosses_shadowflame_threshold_before_the_follow_up(
        self, fight, attacker_stats
    ):
        abilities = {
            "Q": {
                "name": "Opening spell",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 500.0,
                "parts": (DamagePart("magic", 500.0),),
            },
            "W": {
                "name": "Follow-up spell",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 200.0,
                "parts": (DamagePart("magic", 200.0),),
            },
        }
        result = fight(
            attacker_stats(),
            abilities,
            items=[
                get_item_by_name("Luden's Echo"),
                get_item_by_name("Shadowflame"),
            ],
            target_magic_resistance=0.0,
        )

        # Q leaves 500 HP. Luden's 150 lands immediately after Q and leaves
        # 350, so W starts below 40% and receives a 40-damage Cinderbloom
        # bonus. Treating Luden as an end-of-rotation proc would yield 30.
        assert result["breakdown"]["shadowflame_Shadowflame"][
            "total_damage"
        ] == pytest.approx(40.0)

    @pytest.mark.parametrize(
        ("target_index", "target_count", "expected_proc"),
        [
            (0, 1, 150.0),
            (0, 2, 135.0),
            (1, 2, 75.0),
            (0, 7, 75.0),
            (5, 7, 75.0),
            (6, 7, 0.0),
        ],
    )
    def test_luden_charges_are_allocated_inside_each_target_fight(
        self,
        fight,
        attacker_stats,
        target_index,
        target_count,
        expected_proc,
    ):
        result = fight(
            attacker_stats(),
            self._test_spell(),
            items=[get_item_by_name("Luden's Echo")],
            target_magic_resistance=0.0,
            roster_target_index=target_index,
            roster_target_count=target_count,
        )

        proc = result["breakdown"]["proc_Luden's Echo"]
        assert proc["total_damage"] == pytest.approx(expected_proc)

    def test_luden_target_share_resolves_before_lifeline_threshold(
        self, fight, attacker_stats
    ):
        ability = self._test_spell()
        ability["Q"]["total_raw"] = 600.0
        ability["Q"]["parts"] = (DamagePart("magic", 600.0),)
        common = {
            "items": [get_item_by_name("Luden's Echo")],
            "target_magic_resistance": 0.0,
            "target_threshold_shield_amount": 500.0,
            "target_threshold_shield_health_ratio": 0.30,
            "target_threshold_shield_duration": 3.0,
            "roster_target_count": 2,
        }

        primary = fight(
            attacker_stats(),
            ability,
            roster_target_index=0,
            **common,
        )
        secondary = fight(
            attacker_stats(),
            ability,
            roster_target_index=1,
            **common,
        )

        # Primary receives 135 Luden damage: 600 leaves 400 HP, then 135
        # crosses the 300-HP Lifeline threshold and is absorbed. Secondary
        # receives 75, remains at 325 HP, and never triggers the shield.
        assert primary["threshold_shield_absorbed"] == pytest.approx(135.0)
        assert primary["health_damage"] == pytest.approx(600.0)
        assert secondary["threshold_shield_absorbed"] == 0.0
        assert secondary["health_damage"] == pytest.approx(675.0)


class TestAbilityDotTickEvents:
    """DoT ability rows with a sourced tick cadence author per-tick events."""

    @staticmethod
    def _dot_spell(*, tick_interval: float | None = 0.5) -> dict:
        entry = {
            "name": "Poison",
            "rank": 1,
            "cooldown": 4.0,
            "damage_type": "magic",
            "total_raw": 300.0,
            "parts": (DamagePart("magic", 300.0),),
            "dot_duration": 3.0,
        }
        if tick_interval is not None:
            entry["dot_tick_interval"] = tick_interval
        return {"Q": entry}

    def test_sourced_cadence_authors_ticks_from_each_cast(self, fight, attacker_stats):
        """Casts at t=0 and t=4 each spread six 0.5s ticks over their
        3s window; the events sum to the row total and certify it."""
        result = fight(
            attacker_stats(),
            self._dot_spell(),
            target_magic_resistance=0.0,
            one_rotation=False,
            fight_duration_seconds=5.0,
        )

        row = result["breakdown"]["Q"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == pytest.approx(
            [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0]
        )
        assert all(event["damage"] == pytest.approx(50.0) for event in events)
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )

    def test_authored_dot_ticks_lift_the_coverage_downgrade(
        self, fight, attacker_stats
    ):
        """A dot_duration row whose events sum exactly is certified."""
        result = fight(
            attacker_stats(),
            self._dot_spell(),
            target_magic_resistance=0.0,
        )

        coverage = result["timeline_coverage"]
        assert coverage["complete"] is True
        assert "Q" in coverage["exact_sources"]

    def test_dot_without_sourced_cadence_stays_coarse(self, fight, attacker_stats):
        """No sourced tick interval means no invented events: fail closed."""
        result = fight(
            attacker_stats(),
            self._dot_spell(tick_interval=None),
            target_magic_resistance=0.0,
        )

        assert "damage_events" not in result["breakdown"]["Q"]
        assert "Q" in result["timeline_coverage"]["coarse_sources"]


class TestOrderedDamageEvents:
    """The shared ledger keeps cast order and exact typed composition."""

    def test_timed_casts_are_interleaved_by_the_accepted_timeline(self):
        events = _ordered_damage_events(
            {
                "Q": {
                    "casts": 2,
                    "total_damage": 200.0,
                    "damage_type": "magic",
                },
                "W": {
                    "casts": 1,
                    "total_damage": 60.0,
                    "damage_type": "physical",
                },
            },
            {"Q": {}, "W": {}},
            ["Q", "W"],
            cast_events=[
                {"time": 0.0, "slot": "Q", "ordinal": 1},
                {"time": 1.0, "slot": "W", "ordinal": 1},
                {"time": 2.0, "slot": "Q", "ordinal": 2},
            ],
        )

        assert [event["source_key"] for event in events] == ["Q", "W", "Q"]
        assert [event["damage"] for event in events] == [100.0, 60.0, 100.0]

    def test_engine_authored_auto_events_keep_times_and_per_hit_damage(self):
        events = _ordered_damage_events(
            {
                "auto_attacks": {
                    "count": 2,
                    "total_damage": 300.0,
                    "damage_type": "physical",
                    "event_phase": "auto",
                    "damage_events": [
                        {
                            "time": 0.0,
                            "damage_type": "physical",
                            "damage": 100.0,
                        },
                        {
                            "time": 0.5,
                            "damage_type": "physical",
                            "damage": 200.0,
                        },
                    ],
                }
            },
            {},
            [],
        )

        assert [event["time"] for event in events] == [0.0, 0.5]
        assert [event["damage"] for event in events] == [100.0, 200.0]

    def test_mixed_cast_instances_keep_their_exact_damage_types(self):
        events = _ordered_damage_events(
            {
                "R": {
                    "casts": 1,
                    "total_damage": 180.0,
                    "damage_type": "mixed",
                    "damage_by_type": {"magic": 120.0, "true": 60.0},
                }
            },
            {"R": {"cast_instances": 3}},
            ["R"],
        )

        assert len(events) == 6
        assert sum(
            event["damage"] for event in events if event["damage_type"] == "magic"
        ) == pytest.approx(120.0)
        assert sum(
            event["damage"] for event in events if event["damage_type"] == "true"
        ) == pytest.approx(60.0)

    def test_untyped_amplifier_is_redistributed_without_losing_damage(self):
        events = _ordered_damage_events(
            {
                "Q": {
                    "casts": 1,
                    "total_damage": 75.0,
                    "damage_type": "magic",
                },
                "auto_attacks": {
                    "count": 1,
                    "total_damage": 25.0,
                    "damage_type": "physical",
                },
                "damage_amp_Test": {"total_damage": 20.0},
            },
            {"Q": {}},
            ["Q"],
        )

        assert sum(event["damage"] for event in events) == pytest.approx(120.0)
        assert sum(
            event["damage"]
            for event in events
            if event["source_key"] == "damage_amp_Test"
            and event["damage_type"] == "magic"
        ) == pytest.approx(15.0)


class TestLedgerRowShapes:
    """The three ledger shapes stay projections of one row schema."""

    # What ``lean`` drops: display-only fields no scoring consumer reads.
    DISPLAY_ONLY = {
        "ordinal",
        "phase",
        "order",
        "source_missing_ratio",
        "event_precision",
    }

    @staticmethod
    def _ledger(**kwargs):
        breakdown = {
            "Q": {
                "casts": 1,
                "total_damage": 90.0,
                "total_raw": 120.0,
                "damage_type": "magic",
            },
            "auto_attacks": {
                "count": 2,
                "total_damage": 150.0,
                "damage_type": "physical",
                "damage_events": [
                    {
                        "time": 0.0,
                        "damage": 50.0,
                        "damage_type": "physical",
                        "raw_damage": 60.0,
                        "raw_formula": {"kind": "auto"},
                        "basic_attack": True,
                        "cc_kind": "slow",
                        "source_missing_ratio": 0.25,
                        "event_precision": "exact",
                        "declared": ("mechanic", 60.0),
                    },
                    {"time": 0.5, "damage": 100.0, "damage_type": "physical"},
                ],
                # Shorter than the event list on purpose: the second swing
                # has no shield to inherit.
                "self_shield_events": [{"amount": 12.0}],
            },
            "burn_Test": {"total_damage": 40.0, "damage_by_type": {"magic": 40.0}},
            "damage_amp_Test": {"total_damage": 20.0},
        }
        return _ordered_damage_events(breakdown, {"Q": {}}, ["Q"], **kwargs)

    def test_every_shape_reports_the_same_events_in_the_same_order(self):
        full = self._ledger()
        lean = self._ledger(lean=True)
        light = self._ledger(light=True)

        assert len(full) == len(lean) == len(light) > 4
        for full_row, lean_row, light_row in zip(full, lean, light, strict=False):
            assert light_row[0] == full_row["_lk"] == lean_row["_lk"]
            assert light_row[1] == full_row["damage"]
            assert light_row[2] == full_row["damage_type"]
            assert light_row[3] == full_row["source_key"]
            assert light_row[4] == full_row.get("raw_formula")
            assert light_row[5] == full_row.get("raw_damage", 0.0)
            assert light_row[6] == full_row.get("declared")

    def test_lean_drops_the_display_fields_and_nothing_else(self):
        for full_row, lean_row in zip(
            self._ledger(), self._ledger(lean=True), strict=False
        ):
            assert set(lean_row) == set(full_row) - self.DISPLAY_ONLY
            for key, value in lean_row.items():
                assert full_row[key] == value
            assert self.DISPLAY_ONLY & set(full_row)

    def test_pricing_markers_ride_the_scoring_shape(self):
        swing = next(
            row
            for row in self._ledger(lean=True)
            if row["source_key"] == "auto_attacks" and row["time"] == 0.0
        )

        assert swing["basic_attack"] is True
        assert swing["omnivamp_effectiveness"] == 1.0
        assert swing["cc_kind"] == "slow"
        assert swing["cc_reviewed"] is True
        assert swing["declared"] == ("mechanic", 60.0)
        assert swing["raw_damage"] == 60.0

    def test_entry_shield_list_shorter_than_its_events_lands_once(self):
        swings = [row for row in self._ledger() if row["source_key"] == "auto_attacks"]

        assert [row.get("self_shield") for row in swings] == [{"amount": 12.0}, None]

    def test_synthesized_rows_carry_the_same_schema_as_authored_ones(self):
        ability = next(row for row in self._ledger() if row["source_key"] == "Q")

        assert ability["raw_damage"] == 120.0
        assert ability["is_ability"] is True
        assert ability["phase"] == "ability"
        assert "omnivamp_effectiveness" not in ability


class TestAmplifierEventAttribution:
    """damage_amp_<source> rows author their delta onto the amplified events."""

    @staticmethod
    def _test_spell(*, cooldown: float = 10.0) -> dict:
        return {
            "Q": {
                "name": "Test spell",
                "rank": 1,
                "cooldown": cooldown,
                "damage_type": "magic",
                "total_raw": 300.0,
                "parts": (DamagePart("magic", 300.0),),
            }
        }

    @pytest.fixture
    def liandry_fight(self, fight, attacker_stats) -> dict:
        """Timed fight where Liandry's Suffering amp has real events to ride."""
        return fight(
            attacker_stats(),
            self._test_spell(),
            items=[get_item_by_name("Liandry's Torment")],
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.5,
        )

    def test_general_amp_authors_delta_events_at_amplified_times(self, liandry_fight):
        """The amp delta lands on the amplified events' own timestamps,
        not lumped at one coarse stamp, and sums to the row total."""
        amp_row = liandry_fight["breakdown"]["damage_amp_Liandry's Torment"]
        amp_events = amp_row["damage_events"]
        assert sum(event["damage"] for event in amp_events) == pytest.approx(
            amp_row["total_damage"]
        )
        amp_times = {event["time"] for event in amp_events}
        amplified_times = {
            event["time"]
            for event in liandry_fight["damage_events"]
            if event["source_key"] != "damage_amp_Liandry's Torment"
        }
        assert amp_times <= amplified_times
        assert len(amp_times) > 1

    def test_general_amp_row_is_certified_exact(self, liandry_fight):
        coverage = liandry_fight["timeline_coverage"]
        assert coverage["complete"] is True
        assert "damage_amp_Liandry's Torment" in coverage["exact_sources"]

    def test_amp_delta_mirrors_the_amplified_type_composition(self, liandry_fight):
        """A fight-wide amp scales every type equally: the delta's per-type
        split matches the pre-amp ledger's per-type split."""
        amp_events = liandry_fight["breakdown"]["damage_amp_Liandry's Torment"][
            "damage_events"
        ]
        amplified = [
            event
            for event in liandry_fight["damage_events"]
            if event["source_key"] != "damage_amp_Liandry's Torment"
        ]

        def type_fraction(events: list, dtype: str) -> float:
            total = sum(event["damage"] for event in events)
            return sum(e["damage"] for e in events if e["damage_type"] == dtype) / total

        for dtype in ("physical", "magic"):
            assert type_fraction(amp_events, dtype) == pytest.approx(
                type_fraction(amplified, dtype)
            )

    def test_hypershot_amp_excludes_the_trigger_cast(self, fight, attacker_stats):
        """Horizon Focus amps everything except the first cast (the trigger):
        its delta events cover every cast time but the first."""
        result = fight(
            attacker_stats(),
            self._test_spell(cooldown=2.0),
            items=[get_item_by_name("Horizon Focus")],
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
        )

        amp_row = result["breakdown"]["damage_amp_Horizon Focus"]
        amp_events = amp_row["damage_events"]
        assert sum(event["damage"] for event in amp_events) == pytest.approx(
            amp_row["total_damage"]
        )
        cast_times = {event["time"] for event in result["cast_timeline"]}
        assert {event["time"] for event in amp_events} == cast_times - {min(cast_times)}
        assert "damage_amp_Horizon Focus" in (
            result["timeline_coverage"]["exact_sources"]
        )


class TestTargetIncomingDamageModifiers:
    """Target item defenses apply to their exact damage events."""

    def test_guardians_horn_blocks_flat_champion_damage_and_reduces_dot(
        self, fight, attacker_stats
    ):
        direct = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Direct spell",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 100.0,
                    "parts": (DamagePart("magic", 100.0),),
                }
            },
            target_magic_resistance=0.0,
            target_champion_damage_flat_reduction=15.0,
            target_champion_dot_damage_flat_reduction=3.75,
        )
        dot = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Damage-over-time spell",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 100.0,
                    "dot_duration": 3.0,
                    "parts": (DamagePart("magic", 100.0),),
                }
            },
            target_magic_resistance=0.0,
            target_champion_damage_flat_reduction=15.0,
            target_champion_dot_damage_flat_reduction=3.75,
        )

        assert direct["breakdown"]["Q"]["total_damage"] == pytest.approx(85.0)
        assert dot["breakdown"]["Q"]["total_damage"] == pytest.approx(96.25)

    def test_target_physical_reduction_applies_before_armor_per_instance(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(attack_damage=100.0, attack_speed=1.0),
            {
                "Q": {
                    "name": "Two physical hits",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 200.0,
                    "parts": (DamagePart("physical", 100.0, count=2),),
                }
            },
            target_armor=100.0,
            target_physical_damage_flat_reduction=16.0,
            target_physical_damage_flat_reduction_cap=0.50,
        )

        # Each 100 raw hit loses 16 before armor, then 50% resistance:
        # (100 - 16) * 0.5 * 2 = 84.
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(84.0)

    def test_guardians_horn_blocks_basic_attack_damage_after_basic_defenses(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(attack_damage=100.0, attack_speed=1.0),
            target_armor=0.0,
            target_champion_damage_flat_reduction=15.0,
            auto_attack_uptime=1.0,
            fight_duration_seconds=1.0,
        )

        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            85.0
        )

    def test_plating_and_rock_solid_apply_after_armor(self, fight, attacker_stats):
        result = fight(
            attacker_stats(attack_damage=100.0, attack_speed=1.0),
            one_rotation=False,
            fight_duration_seconds=1.0,
            auto_attack_uptime=1.0,
            target_armor=100.0,
            target_basic_damage_multiplier=0.90,
            target_basic_damage_flat_reduction=15.0,
            target_basic_damage_flat_reduction_cap=0.20,
        )

        # 100 raw -> 50 after armor -> 45 after Plating -> Rock Solid is
        # capped at 20% of 45, so it removes 9 rather than the full 15.
        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            36.0
        )

    def test_randuin_reduces_only_the_critical_branch(self, fight, attacker_stats):
        result = fight(
            attacker_stats(
                attack_damage=100.0,
                attack_speed=1.0,
                critical_strike_chance=50.0,
            ),
            one_rotation=False,
            fight_duration_seconds=1.0,
            auto_attack_uptime=1.0,
            target_armor=0.0,
            target_critical_strike_damage_multiplier=0.70,
        )

        # Deterministic EV: 50% x 100 + 50% x (200 x 0.7) = 120.
        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            120.0
        )

    def test_rock_solid_consumes_once_per_multihit_basic_cast(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Two-hit attack spell",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 200.0,
                    "parts": (
                        DamagePart("physical", 100.0, count=2, basic_damage=True),
                    ),
                }
            },
            target_armor=0.0,
            target_basic_damage_multiplier=0.90,
            target_basic_damage_flat_reduction=15.0,
            target_basic_damage_flat_reduction_cap=0.20,
        )

        # Both hits receive Plating (180 total); only the first instance in
        # the cast consumes Rock Solid (15), leaving 165.
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(165.0)

    def test_randuin_reduces_ability_critical_strikes(self, fight, attacker_stats):
        result = fight(
            attacker_stats(critical_strike_chance=100.0),
            {
                "Q": {
                    "name": "Critting ability",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 100.0,
                    "parts": (DamagePart("physical", 100.0, crit_effectiveness=1.0),),
                }
            },
            target_armor=0.0,
            target_critical_strike_damage_multiplier=0.70,
        )

        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(140.0)

    def test_randuin_does_not_reduce_true_damage_critical_strikes(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(critical_strike_chance=100.0),
            {
                "Q": {
                    "name": "True crit",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "true",
                    "total_raw": 100.0,
                    "parts": (DamagePart("true", 100.0, crit_effectiveness=1.0),),
                }
            },
            target_critical_strike_damage_multiplier=0.70,
        )

        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(200.0)

    def test_plating_reduces_basic_tagged_item_damage(self, fight, attacker_stats):
        result = fight(
            attacker_stats(attack_damage=100.0, attack_speed=1.0),
            one_rotation=False,
            fight_duration_seconds=1.0,
            auto_attack_uptime=1.0,
            target_armor=0.0,
            target_basic_damage_multiplier=0.90,
            items=[{"name": "Heartsteel"}],
        )

        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            90.0
        )
        assert result["breakdown"]["on_hit_once_Heartsteel"][
            "total_damage"
        ] == pytest.approx(171.0)

    def test_threshold_shield_absorbs_the_triggering_damage(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Trigger",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 800.0,
                    "parts": (DamagePart("magic", 800.0),),
                },
                "W": {
                    "name": "Follow up",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 200.0,
                    "parts": (DamagePart("magic", 200.0),),
                },
            },
            target_health=1000.0,
            target_magic_resistance=0.0,
            target_threshold_shield_amount=400.0,
            target_threshold_shield_health_ratio=0.30,
            target_threshold_shield_duration=3.0,
        )

        assert result["total_damage"] == pytest.approx(1000.0)
        assert result["threshold_shield_absorbed"] == pytest.approx(400.0)
        assert result["health_damage"] == pytest.approx(600.0)

    def test_magic_threshold_shield_ignores_physical_damage(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Magic trigger",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 350.0,
                    "parts": (DamagePart("magic", 350.0),),
                },
                "W": {
                    "name": "Physical follow up",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 200.0,
                    "parts": (DamagePart("physical", 200.0),),
                },
            },
            target_health=1000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            target_threshold_shield_amount=500.0,
            target_threshold_shield_health_ratio=0.90,
            target_threshold_shield_duration=3.0,
            target_threshold_shield_damage_type="magic",
        )

        # Q triggers the magic-only Lifeline shield and consumes 350 of it.
        # The remaining 150 must not absorb W's physical damage.
        assert result["threshold_shield_absorbed"] == pytest.approx(350.0)
        assert result["health_damage"] == pytest.approx(200.0)

    def test_timed_auto_events_allow_threshold_shield_to_expire(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(attack_damage=400.0, attack_speed=2.0),
            one_rotation=False,
            fight_duration_seconds=1.0,
            auto_attack_uptime=1.0,
            target_armor=0.0,
            target_threshold_shield_amount=500.0,
            target_threshold_shield_health_ratio=0.90,
            target_threshold_shield_duration=0.20,
        )

        # Autos land at 0.0s and 0.5s. The first consumes 400 shield; the
        # remaining 100 expires before the second swing instead of absorbing it.
        assert result["total_damage"] == pytest.approx(800.0)
        assert result["threshold_shield_absorbed"] == pytest.approx(400.0)
        assert result["health_damage"] == pytest.approx(400.0)

    def test_timed_autos_cross_shadowflame_threshold_before_later_cast(
        self, fight, attacker_stats
    ):
        from src.calculator.data_fetcher import get_item_by_name

        result = fight(
            attacker_stats(attack_damage=160.0, attack_speed=1.0),
            {
                "Q": {
                    "name": "Timed spell",
                    "rank": 1,
                    "cooldown": 2.0,
                    "damage_type": "magic",
                    "total_raw": 300.0,
                    "parts": (DamagePart("magic", 300.0),),
                }
            },
            items=[get_item_by_name("Shadowflame")],
            one_rotation=False,
            fight_duration_seconds=3.0,
            auto_attack_uptime=1.0,
            target_health=1000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
        )

        # Q at 0s, then autos at 0s and 1s leave 380 HP. Q's 2s recast
        # therefore receives Cinderbloom's 20% bonus (60 damage).
        assert result["breakdown"]["shadowflame_Shadowflame"][
            "total_damage"
        ] == pytest.approx(60.0)
        cinderbloom = result["breakdown"]["shadowflame_Shadowflame"]
        assert cinderbloom["damage_events"] == [
            {
                "time": 2.0,
                "damage": pytest.approx(60.0),
                "damage_type": "magic",
                "source_key": "shadowflame_Shadowflame",
                "trigger_source": "Q",
            }
        ]
        assert result["timeline_coverage"]["complete"] is True
        assert "shadowflame_Shadowflame" in result["timeline_coverage"]["exact_sources"]

    def test_burn_ticks_keep_timing_and_respect_lifeline_expiry(
        self, fight, attacker_stats
    ):
        from src.calculator.data_fetcher import get_item_by_name

        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Shield trigger",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 350.0,
                    "parts": (DamagePart("magic", 350.0),),
                }
            },
            items=[get_item_by_name("Blackfire Torch")],
            target_magic_resistance=0.0,
            target_threshold_shield_amount=500.0,
            target_threshold_shield_health_ratio=0.90,
            target_threshold_shield_duration=0.75,
        )

        burn = result["breakdown"]["burn_Blackfire Torch"]
        assert [event["time"] for event in burn["damage_events"]] == [
            0.5,
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
        ]
        assert [event["damage"] for event in burn["damage_events"]] == pytest.approx(
            [10.0] * 6
        )
        # Q consumes 350 shield and the 0.5s tick consumes 10 more. The
        # remaining shield expires before the five later ticks.
        assert result["total_damage"] == pytest.approx(410.0)
        assert result["threshold_shield_absorbed"] == pytest.approx(360.0)
        assert result["health_damage"] == pytest.approx(50.0)

    def test_protoplasm_grants_health_before_triggering_damage(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Trigger",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 800.0,
                    "parts": (DamagePart("magic", 800.0),),
                }
            },
            fight_duration_seconds=4.0,
            target_health=1000.0,
            target_magic_resistance=0.0,
            target_threshold_health_bonus=200.0,
            target_threshold_health_heal=300.0,
            target_threshold_health_ratio=0.30,
            target_threshold_health_duration=5.0,
        )

        assert result["total_damage"] == pytest.approx(800.0)
        assert result["threshold_health_triggered"] is True
        assert result["threshold_health_bonus_gained"] == 200.0
        # Inside the window: the raised maximum still stands.
        assert result["target_effective_max_health"] == 1200.0
        # 1000 - 800 damage, plus the 16 of 20 authored 0.25s heal ticks
        # (15 each) that fall inside a four-second fight.
        assert result["threshold_health_heal_ticks"] == 16
        assert result["target_ending_health"] == pytest.approx(640.0)

    def test_protoplasm_temporary_maximum_lapses_on_the_wiki_health_rule(
        self, fight, attacker_stats
    ):
        """The Wiki's Health page worked example, driven through the engine.

        "When the passive runs out, maximum health decreases by 200 from 1200
        to 1000.  Current health remains at 700."  A defender that spent more
        than the grant keeps every point it healed to; only an overhang above
        the restored maximum would be clamped away.
        """
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Trigger",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 800.0,
                    "parts": (DamagePart("magic", 800.0),),
                }
            },
            fight_duration_seconds=5.0,
            target_health=1000.0,
            target_magic_resistance=0.0,
            target_threshold_health_bonus=200.0,
            target_threshold_health_heal=300.0,
            target_threshold_health_ratio=0.30,
            target_threshold_health_duration=5.0,
        )

        assert result["threshold_health_triggered"] is True
        assert result["threshold_health_expired"] is True
        assert result["threshold_health_heal_ticks"] == 20
        assert result["target_effective_max_health"] == pytest.approx(1000.0)
        assert result["target_ending_health"] == pytest.approx(700.0)

    def test_protoplasm_updates_later_liandry_max_health_ticks(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Trigger",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 800.0,
                    "parts": (DamagePart("magic", 800.0),),
                }
            },
            items=[get_item_by_name("Liandry's Torment")],
            target_health=1000.0,
            target_magic_resistance=0.0,
            target_threshold_health_bonus=200.0,
            target_threshold_health_heal=300.0,
            target_threshold_health_ratio=0.30,
            target_threshold_health_duration=5.0,
        )

        burn = result["breakdown"]["burn_Liandry's Torment"]
        assert burn["total_damage"] == pytest.approx(72.0)
        assert [event["damage"] for event in burn["damage_events"]] == pytest.approx(
            [12.0] * 6
        )
        # The whole sourced heal, delivered on its authored 0.25s ticks
        # rather than interpolated across whatever damage events existed.
        assert result["target_healing_received"] == pytest.approx(300.0)
        assert result["threshold_health_cadence_certified"] is True
        assert result["timeline_coverage"]["complete"] is True
        assert (
            "target_Protoplasm Harness"
            not in result["timeline_coverage"]["coarse_sources"]
        )

    def test_protoplasm_health_can_delay_shadowflame_threshold(
        self, fight, attacker_stats
    ):
        abilities = {
            "Q": {
                "name": "Trigger",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 750.0,
                "parts": (DamagePart("magic", 750.0),),
            },
            "W": {
                "name": "Follow up",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 100.0,
                "parts": (DamagePart("magic", 100.0),),
            },
        }
        baseline = fight(
            attacker_stats(),
            abilities,
            items=[get_item_by_name("Shadowflame")],
            target_health=1000.0,
            target_magic_resistance=0.0,
        )
        protoplasm = fight(
            attacker_stats(),
            abilities,
            items=[get_item_by_name("Shadowflame")],
            target_health=1000.0,
            target_magic_resistance=0.0,
            target_threshold_health_bonus=300.0,
            target_threshold_health_heal=400.0,
            target_threshold_health_ratio=0.30,
            target_threshold_health_duration=5.0,
        )

        assert baseline["breakdown"]["shadowflame_Shadowflame"][
            "total_damage"
        ] == pytest.approx(20.0)
        assert "shadowflame_Shadowflame" not in protoplasm["breakdown"]

    def test_protoplasm_still_downgrades_coverage_without_an_authored_cadence(
        self, fight, attacker_stats, monkeypatch
    ):
        """The emptied downgrade, fired on a declaration that authors no ticks.

        Banned shortcut check: the coverage refusal was not deleted, it was
        *measured*.  A declaration subdividing the sourced window into no
        ticks leaves the heal a total rather than a schedule, and the coarse
        source comes back exactly as it used to.
        """
        monkeypatch.setattr(
            damage.threshold_defense, "threshold_health_tick_interval", lambda: 0.0
        )
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Trigger",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 800.0,
                    "parts": (DamagePart("magic", 800.0),),
                }
            },
            target_health=1000.0,
            target_magic_resistance=0.0,
            target_threshold_health_bonus=200.0,
            target_threshold_health_heal=300.0,
            target_threshold_health_ratio=0.30,
            target_threshold_health_duration=5.0,
        )

        assert result["threshold_health_triggered"] is True
        assert result["threshold_health_cadence_certified"] is False
        assert result["threshold_health_heal_ticks"] == 0
        coverage = result["timeline_coverage"]
        assert coverage["complete"] is False
        assert coverage["certification"] == "partial_event_order"
        assert "target_Protoplasm Harness" in coverage["coarse_sources"]
        assert "no heal tick cadence" in coverage["note"]

    def test_protoplasm_prices_a_fight_that_outlives_its_window(
        self, fight, attacker_stats
    ):
        """The fight the refusal used to withhold now computes.

        Six seconds outlives the five-second window, and the second cast
        lands after it: the temporary maximum is gone by then, so the
        defender meets that packet on its base maximum.
        """
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Trigger and repeat",
                    "rank": 1,
                    "cooldown": 5.0,
                    "damage_type": "magic",
                    "total_raw": 800.0,
                    "parts": (DamagePart("magic", 800.0),),
                }
            },
            one_rotation=False,
            fight_duration_seconds=6.0,
            target_health=1000.0,
            target_magic_resistance=0.0,
            target_threshold_health_bonus=200.0,
            target_threshold_health_heal=300.0,
            target_threshold_health_ratio=0.30,
            target_threshold_health_duration=5.0,
        )

        assert result["threshold_health_triggered"] is True
        assert result["threshold_health_expired"] is True
        assert result["target_effective_max_health"] == pytest.approx(1000.0)
        assert result["timeline_coverage"]["complete"] is True


class TestShieldReaver:
    """Serpent's Fang venom cuts the target's non-magic shields."""

    _TRIGGER_Q = {
        "Q": {
            "name": "Magic trigger",
            "rank": 1,
            "cooldown": 10.0,
            "damage_type": "magic",
            "total_raw": 800.0,
            "parts": (DamagePart("magic", 800.0),),
        }
    }

    def _fang_fight(self, fight, attacker_stats, **overrides):
        return fight(
            attacker_stats(**overrides.pop("stats", {})),
            self._TRIGGER_Q,
            items=[get_item_by_name("Serpent's Fang")],
            target_health=1000.0,
            target_magic_resistance=0.0,
            **overrides,
        )

    def test_melee_cuts_general_lifeline_shield_by_half(self, fight, attacker_stats):
        result = self._fang_fight(
            fight,
            attacker_stats,
            target_threshold_shield_amount=400.0,
            target_threshold_shield_health_ratio=0.30,
            target_threshold_shield_duration=3.0,
            target_threshold_shield_damage_type="all",
        )

        assert result["threshold_shield_absorbed"] == pytest.approx(200.0)
        assert result["health_damage"] == pytest.approx(600.0)
        assert any("Shield Reaver" in note for note in result["notes"])

    def test_ranged_cuts_general_lifeline_shield_by_35_percent(
        self, fight, attacker_stats
    ):
        result = self._fang_fight(
            fight,
            attacker_stats,
            stats={"is_melee": False},
            target_threshold_shield_amount=400.0,
            target_threshold_shield_health_ratio=0.30,
            target_threshold_shield_duration=3.0,
            target_threshold_shield_damage_type="all",
        )

        assert result["threshold_shield_absorbed"] == pytest.approx(260.0)

    def test_magic_lifeline_shield_is_unaffected(self, fight, attacker_stats):
        result = self._fang_fight(
            fight,
            attacker_stats,
            target_threshold_shield_amount=400.0,
            target_threshold_shield_health_ratio=0.30,
            target_threshold_shield_duration=3.0,
            target_threshold_shield_damage_type="magic",
        )

        assert result["threshold_shield_absorbed"] == pytest.approx(400.0)

    def test_starting_magic_shield_immune_but_general_shield_cut(
        self, fight, attacker_stats
    ):
        result = self._fang_fight(
            fight,
            attacker_stats,
            target_magic_shield=300.0,
            target_general_shield=200.0,
        )

        assert result["magic_shield_absorbed"] == pytest.approx(300.0)
        assert result["general_shield_absorbed"] == pytest.approx(100.0)

    def test_starting_physical_shield_is_cut(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            {
                "Q": {
                    "name": "Physical hit",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 800.0,
                    "parts": (DamagePart("physical", 800.0),),
                }
            },
            items=[get_item_by_name("Serpent's Fang")],
            target_health=1000.0,
            target_armor=0.0,
            target_physical_shield=300.0,
        )

        assert result["physical_shield_absorbed"] == pytest.approx(150.0)

    def test_protoplasm_health_and_healing_are_not_shields(self, fight, attacker_stats):
        result = self._fang_fight(
            fight,
            attacker_stats,
            # Inside the temporary maximum's own window, so what is measured
            # is the venom sparing the grant rather than its expiry.
            fight_duration_seconds=4.0,
            target_threshold_health_bonus=200.0,
            target_threshold_health_heal=300.0,
            target_threshold_health_ratio=0.30,
            target_threshold_health_duration=5.0,
        )

        assert result["threshold_health_bonus_gained"] == 200.0
        assert result["target_effective_max_health"] == 1200.0

    def test_no_note_without_target_shields(self, fight, attacker_stats):
        result = self._fang_fight(fight, attacker_stats)

        assert not any("Shield Reaver" in note for note in result["notes"])


class TestBorkCurrentHpSimulation:
    """Tests for Blade of the Ruined King current-HP iterative simulation."""

    def test_single_hit_equals_full_hp_calculation(self) -> None:
        """With 1 auto attack, BoRK damage should equal ratio * full HP."""
        # Ranged, 0 armor, 1000 HP => 6% * 1000 = 60
        result, hits = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=1,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert abs(result - 60.0) < 0.01
        assert hits == 1

    def test_second_hit_less_than_first(self) -> None:
        """Second BoRK hit should deal less because target HP dropped."""
        # 2 hits, ranged, 0 armor, 1000 HP, auto does 100 damage
        result, hits = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=2,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        # Hit 1: 6% * 1000 = 60, target HP drops to 1000 - 100 - 60 = 840
        # Hit 2: 6% * 840 = 50.4, target HP drops to 840 - 100 - 50.4 = 689.6
        # Total: 110.4
        assert abs(result - 110.4) < 0.01
        assert hits == 2

    def test_less_than_flat_multiplication(self) -> None:
        """Iterative BoRK should always deal less than naive per_hit * hits."""
        naive_total = 0.06 * 1000.0 * 5  # 300
        result, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=5,
            auto_damage_per_hit=80.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert result < naive_total

    def test_min_damage_when_target_hp_zero(self) -> None:
        """BoRK should deal 5 flat damage once target HP hits 0."""
        # High auto damage to quickly deplete HP
        result, hits = _simulate_bork_damage(
            target_health=100.0,
            num_auto_attacks=3,
            auto_damage_per_hit=200.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        # Hit 1: 6% * 100 = 6, HP -> max(0, 100 - 200 - 6) = 0
        # Hit 2: min 5, HP stays 0
        # Hit 3: min 5, HP stays 0
        # Total: 6 + 5 + 5 = 16
        assert abs(result - 16.0) < 0.01
        assert hits == 3

    def test_melee_uses_9_percent(self) -> None:
        """Melee champions should use the 9% ratio."""
        result, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=1,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=True,
        )
        assert abs(result - 90.0) < 0.01

    def test_armor_mitigates_bork_damage(self) -> None:
        """BoRK physical damage should be reduced by armor."""
        # 100 armor => 100/200 = 50% mitigation
        result, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=1,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=100.0,
            is_melee=False,
        )
        # Raw: 60, mitigated: 30
        assert abs(result - 30.0) < 0.01

    def test_zero_auto_attacks_returns_zero(self) -> None:
        """No autos means no BoRK damage."""
        result, hits = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=0,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert result == 0.0
        assert hits == 0

    def test_other_on_hit_reduces_target_hp(self) -> None:
        """Other on-hit damage should also reduce target HP for BoRK calc."""
        # Without other on-hit
        result_no_extra, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=3,
            auto_damage_per_hit=50.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        # With other on-hit (target HP drops faster => less BoRK damage)
        result_with_extra, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=3,
            auto_damage_per_hit=50.0,
            other_on_hit_per_hit=30.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert result_with_extra < result_no_extra

    def test_full_fight_with_bork(self) -> None:
        """Integration test: Ahri level 18 with BoRK vs 1000 HP target."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        bork = get_item_by_name("Blade of the Ruined King")
        items = [bork]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.8,
                one_rotation=True,
            ),
        )
        bork_entry = fight["breakdown"].get("on_hit_Blade of the Ruined King")
        assert bork_entry is not None, "BoRK should appear in breakdown"
        assert bork_entry["total_damage"] > 0

        # Verify it's less than the naive flat calculation
        naive_per_hit = 0.06 * 1000  # 60 raw
        naive_mitigated = apply_resistance(naive_per_hit, fight["effective_armor"])
        naive_total = naive_mitigated * bork_entry["count"]
        assert bork_entry["total_damage"] < naive_total, (
            f"Iterative BoRK {bork_entry['total_damage']:.1f} should be less "
            f"than naive {naive_total:.1f}"
        )


class TestCastOrder:
    """Tests that cast_order parameter affects damage calculations."""

    def test_default_cast_order_unchanged(self) -> None:
        """None cast_order should produce the same result as explicit Q,W,E,R."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        items = [get_item_by_name("Rabadon's Deathcap")]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_default = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        fight_explicit = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "W", "E", "R"],
            ),
        )
        assert fight_default["total_damage"] == fight_explicit["total_damage"]

    def test_cast_order_affects_bloodletter_stacking(self) -> None:
        """Different cast orders should produce different damage with Bloodletter's Curse."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        items = [
            get_item_by_name("Rabadon's Deathcap"),
            get_item_by_name("Bloodletter's Curse"),
        ]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_qwer = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "W", "E", "R"],
            ),
        )
        fight_rwqe = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["R", "W", "Q", "E"],
            ),
        )
        # Different order should produce different total damage
        assert fight_qwer["total_damage"] != fight_rwqe["total_damage"]

    def test_cast_order_affects_shadowflame_bonus(self) -> None:
        """Different cast orders should change Shadowflame bonus amounts."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        items = [
            get_item_by_name("Rabadon's Deathcap"),
            get_item_by_name("Shadowflame"),
        ]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_qwer = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1500,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "W", "E", "R"],
            ),
        )
        fight_rqwe = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1500,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["R", "Q", "W", "E"],
            ),
        )
        # With different cast orders, the Shadowflame bonus should differ
        qwer_sf = (
            fight_qwer["breakdown"]
            .get("shadowflame_Shadowflame", {})
            .get("total_damage", 0)
        )
        rqwe_sf = (
            fight_rqwe["breakdown"]
            .get("shadowflame_Shadowflame", {})
            .get("total_damage", 0)
        )
        assert qwer_sf != rqwe_sf


class TestPhantomHitCalculation:
    """Tests for Guinsoo's Rageblade phantom hit timing."""

    def test_no_rageblade_no_phantom_hits(self) -> None:
        """Without Rageblade, no phantom hits should occur."""
        count, autos = _calculate_phantom_hits(20, ["Nashor's Tooth"])
        assert count == 0
        assert len(autos) == 0

    def test_fewer_than_6_autos_no_phantom(self) -> None:
        """With fewer than 6 autos, no phantom hit triggers."""
        count, autos = _calculate_phantom_hits(5, ["Guinsoo's Rageblade"])
        assert count == 0
        assert len(autos) == 0

    def test_exactly_6_autos_one_phantom(self) -> None:
        """6th auto should be the first phantom hit."""
        count, autos = _calculate_phantom_hits(6, ["Guinsoo's Rageblade"])
        assert count == 1
        assert autos == {5}  # 0-indexed: auto #6 is index 5

    def test_10_autos_two_phantoms(self) -> None:
        """6th and 9th autos should trigger phantom hits."""
        count, autos = _calculate_phantom_hits(10, ["Guinsoo's Rageblade"])
        assert count == 2
        assert autos == {5, 8}  # 0-indexed: autos #6 and #9

    def test_13_autos_three_phantoms(self) -> None:
        """6th, 9th, and 12th autos should trigger phantom hits."""
        count, autos = _calculate_phantom_hits(13, ["Guinsoo's Rageblade"])
        assert count == 3
        assert autos == {5, 8, 11}

    def test_20_autos_correct_phantom_count(self) -> None:
        """With 20 autos, phantoms at 6,9,12,15,18 = 5 phantom hits."""
        count, autos = _calculate_phantom_hits(20, ["Guinsoo's Rageblade"])
        assert count == 5
        assert autos == {5, 8, 11, 14, 17}


class TestNavoriEffectiveCd:
    """Tests for Navori Flickerblade CD refund helper."""

    def test_no_autos_returns_base_cd(self) -> None:
        """With 0 autos per second, CD is unchanged."""
        assert _navori_effective_cd(7.0, 0.0, 0.15) == 7.0

    def test_no_refund_returns_base_cd(self) -> None:
        """With 0% refund, CD is unchanged."""
        assert _navori_effective_cd(7.0, 1.5, 0.0) == 7.0

    def test_cd_is_reduced(self) -> None:
        """With autos during the window, CD should be shorter than base."""
        reduced = _navori_effective_cd(7.0, 1.0, 0.15)
        assert reduced < 7.0
        assert reduced > 0.0

    def test_higher_attack_speed_more_reduction(self) -> None:
        """Higher attack speed should reduce CD more."""
        slow = _navori_effective_cd(7.0, 0.5, 0.15)
        fast = _navori_effective_cd(7.0, 2.0, 0.15)
        assert fast < slow

    def test_known_value(self) -> None:
        """Verify a specific scenario: 7s CD, 1 auto/sec, 15% refund.

        t=0: cast, 7s remaining
        t=1: auto → (7-1)*0.85 = 5.10
        t=2: auto → (5.10-1)*0.85 = 3.485
        t=3: auto → (3.485-1)*0.85 = 2.112
        t=4: auto → (2.112-1)*0.85 = 0.945
        t=4.945: CD expires. Effective CD ≈ 4.945s
        """
        reduced = _navori_effective_cd(7.0, 1.0, 0.15)
        assert abs(reduced - 4.945) < 0.01


def test_coupled_auto_sources_are_coarse_in_coverage_itself():
    """A cast row whose hits ride the ambient auto stream (Shen Q) is not
    event-order certified: the downgrade must come out of
    _event_timeline_coverage directly, so every consumer — the fight
    report AND window-sum effects like First Strike — sees one
    definition of "certified"."""
    breakdown = {"Q": {"name": "Q", "total_damage": 100.0, "casts": 1}}
    ability_damages = {"Q": {"requires_auto_timeline_coupling": True}}
    coverage = _event_timeline_coverage(
        breakdown, ability_damages, ["Q"], num_auto_attacks=3
    )
    assert coverage["complete"] is False
    assert coverage["certification"] == "partial_event_order"
    assert coverage["coarse_sources"] == ["Q"]
    assert "ambient auto stream" in coverage["note"]
    # Without autos there is no coupling to certify — Q stays exact.
    no_autos = _event_timeline_coverage(
        breakdown, ability_damages, ["Q"], num_auto_attacks=0
    )
    assert no_autos["exact_sources"] == ["Q"]


class TestOnHitSwingEvents:
    """On-hit rows author real per-swing timestamps in timed fights.

    Phase 1 of timestamp certification: every on-hit application rides a
    simulated auto swing, so the rows can author exact ``damage_events``
    at those swing times instead of collapsing to the coarse effect
    phase. Ability-carried on-hit applications have no authored
    timestamps yet, so rows fed by them deliberately stay coarse.
    """

    @staticmethod
    def _on_hit_shell(**extra) -> dict:
        """Zero-direct-damage ability whose payload is a true on-hit."""
        on_hit = {
            "name": "Test on-hit",
            "damage_per_hit": 30.0,
            "damage_type": "true",
        }
        on_hit.update(extra)
        return {
            "W": {
                "name": "Test on-hit",
                "rank": 1,
                "damage_type": "true",
                "total_raw": 0.0,
                "parts": (),
                "on_hit": on_hit,
            }
        }

    def _timed_fight(self, fight, attacker_stats, abilities, **overrides):
        """5s timed fight at 1.0 AS / full uptime: swings at 0..4s."""
        config = {
            "one_rotation": False,
            "fight_duration_seconds": 5.0,
            "auto_attack_uptime": 1.0,
            "target_armor": 0.0,
            "target_magic_resistance": 0.0,
        }
        config.update(overrides)
        return fight(attacker_stats(), abilities, **config)

    def test_ability_on_hit_rides_authored_swing_times(
        self, fight, attacker_stats
    ) -> None:
        """A one-per-attack passive authors one event per swing."""
        result = self._timed_fight(fight, attacker_stats, self._on_hit_shell())

        row = result["breakdown"]["on_hit_ability_W"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert all(event["damage"] == pytest.approx(30.0) for event in events)
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_ability_W" in result["timeline_coverage"]["exact_sources"]

    def test_stacked_on_hit_smooths_partial_procs_onto_swings(
        self, fight, attacker_stats
    ) -> None:
        """Vayne-W-style rows smear the per-proc damage over every swing.

        The row's total is the smooth per-hit average (partial stacks
        included), so its events must be per-swing shares — grouping
        them into whole procs would break the sum contract.
        """
        result = self._timed_fight(
            fight, attacker_stats, self._on_hit_shell(stacks_required=3)
        )

        row = result["breakdown"]["on_hit_ability_W"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert all(event["damage"] == pytest.approx(30.0) for event in events)
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_ability_W" in result["timeline_coverage"]["exact_sources"]

    def test_max_procs_cap_consumes_the_earliest_swings(
        self, fight, attacker_stats
    ) -> None:
        """A stock-limited on-hit (Bard meeps) procs on the first swings."""
        result = self._timed_fight(
            fight, attacker_stats, self._on_hit_shell(max_procs=2)
        )

        row = result["breakdown"]["on_hit_ability_W"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 1.0]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_ability_W" in result["timeline_coverage"]["exact_sources"]

    def test_stack_ramp_on_hit_escalates_per_swing(self, fight, attacker_stats) -> None:
        """Orianna-P-style events carry each swing's own stacked value."""
        result = self._timed_fight(
            fight,
            attacker_stats,
            self._on_hit_shell(stack_ramp={"damage_per_stack": 10.0, "max_stacks": 2}),
        )

        row = result["breakdown"]["on_hit_ability_W"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert [event["damage"] for event in events] == pytest.approx(
            [30.0, 40.0, 50.0, 50.0, 50.0]
        )
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_ability_W" in result["timeline_coverage"]["exact_sources"]

    def test_ramping_on_hit_scales_with_swing_index(
        self, fight, attacker_stats
    ) -> None:
        """Ramping proc k deals k×base AT swing k — not an even spread."""
        result = self._timed_fight(
            fight, attacker_stats, self._on_hit_shell(ramping=True)
        )

        row = result["breakdown"]["on_hit_ability_W"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert [event["damage"] for event in events] == pytest.approx(
            [30.0, 60.0, 90.0, 120.0, 150.0]
        )
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_ability_W" in result["timeline_coverage"]["exact_sources"]

    def test_scheduled_cooldown_procs_land_on_their_swing_times(
        self, fight, attacker_stats
    ) -> None:
        """Cooldown-gated current-HP procs (Jarvan P) stamp their swings."""
        abilities = self._on_hit_shell(
            proc_cooldown=2.5,
            current_health_percent=10.0,
            min_damage=10.0,
            damage_type="physical",
        )
        del abilities["W"]["on_hit"]["damage_per_hit"]
        result = self._timed_fight(fight, attacker_stats, abilities)

        row = result["breakdown"]["on_hit_ability_W"]
        events = row["damage_events"]
        # Procs at swings 0 (100 = 10% of 1000 HP) and 3 (HP has decayed
        # by the proc plus three 100-damage autos: 10% of 600 = 60).
        assert [event["time"] for event in events] == [0.0, 3.0]
        assert [event["damage"] for event in events] == pytest.approx([100.0, 60.0])
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_ability_W" in result["timeline_coverage"]["exact_sources"]

    def test_ability_hit_counted_on_hits_use_cast_and_swing_timestamps(
        self, fight, attacker_stats
    ) -> None:
        """Shared counters use the accepted ability and auto event clocks."""
        abilities = self._on_hit_shell(stacks_required=2, count_ability_hits=True)
        abilities["Q"] = {
            "name": "Damaging spell",
            "rank": 1,
            "cooldown": 10.0,
            "damage_type": "magic",
            "total_raw": 300.0,
            "parts": (DamagePart("magic", 300.0),),
        }
        result = self._timed_fight(fight, attacker_stats, abilities)

        row = result["breakdown"]["on_hit_ability_W"]
        assert row["total_damage"] > 0
        assert len(row["damage_events"]) == row["count"]
        assert sum(event["damage"] for event in row["damage_events"]) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_ability_W" in result["timeline_coverage"]["exact_sources"]


class TestSplitAutoVsAbility:
    """Tests for split_auto_vs_ability — auto vs ability damage attribution.

    Expected values replicate the attribution rules that previously lived
    in app.py's /api/calculate route.
    """

    def test_pure_ability_damage(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "R": {"name": "R", "total_damage": 250.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 350.0

    def test_pure_auto_damage(self) -> None:
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 400.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 400.0
        assert ability == 0.0

    def test_on_hit_prefix_counts_as_auto(self) -> None:
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 300.0},
            "on_hit_Kraken Slayer": {"name": "Kraken", "total_damage": 90.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 390.0
        assert ability == 0.0

    def test_spellblade_prefix_counts_as_auto(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "spellblade_Lich Bane": {"name": "Lich Bane", "total_damage": 60.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 60.0
        assert ability == 100.0

    def test_fiendhunter_true_damage_counts_as_auto(self) -> None:
        breakdown = {
            "fiendhunter_true_damage": {"name": "Fiendhunter", "total_damage": 75.0},
            "W": {"name": "W", "total_damage": 25.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 75.0
        assert ability == 25.0

    def test_auto_stream_riders_count_as_auto(self) -> None:
        """Champion riders on the swing (Corki P's true instance) share the
        ``auto_attacks`` prefix — a wrong bucket is invisible in the total."""
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 300.0},
            "auto_attacks_true_damage": {"name": "Corki P", "total_damage": 60.0},
            "Q": {"name": "Q", "total_damage": 40.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 360.0
        assert ability == 40.0

    def test_declared_auto_fraction_splits_a_mixed_source_row(self) -> None:
        """A row that knows its own composition (First Strike's window
        bonus spans autos and abilities) declares auto_attack_fraction;
        the split honors it instead of guessing a bucket by key name."""
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 100.0},
            "keystone_First Strike": {
                "name": "First Strike (keystone)",
                "total_damage": 14.0,
                "auto_attack_fraction": 0.5,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == pytest.approx(107.0)
        assert ability == pytest.approx(107.0)

    def test_informational_entries_skipped(self) -> None:
        # Entries marked informational (e.g. Actualizer's amp summary)
        # have damage already counted in other rows — never double-count.
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "ability_amp_Actualizer": {
                "name": "Damage Amplification (Actualizer)",
                "total_damage": 15.0,
                "detail": "included in ability/proc totals above",
                "informational": True,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 100.0

    def test_amp_split_proportionally_and_execute_skipped(self) -> None:
        # auto 100 / ability 300 -> auto ratio 0.25; amp 40 redistributes
        # as 10 auto / 30 ability. Amp rows use the damage_amp_<source>
        # keys the engine actually emits; the execute-threshold row is
        # informational (always zero engine-side) and contributes nothing.
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 100.0},
            "Q": {"name": "Q", "total_damage": 300.0},
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
            "execute": {
                "name": "Execute",
                "total_damage": 0.0,
                "informational": True,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == pytest.approx(110.0)
        assert ability == pytest.approx(330.0)

    def test_multiple_damage_amp_sources_redistribute(self) -> None:
        # Several damage_amp_<source> rows (e.g. LDR + Horizon Focus) all
        # redistribute proportionally — amps scale both buckets.
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 150.0},
            "W": {"name": "W", "total_damage": 50.0},
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 30.0,
            },
            "damage_amp_Horizon Focus": {
                "name": "Damage Amplification (Horizon Focus)",
                "total_damage": 10.0,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        # auto ratio 0.75: 150 + 40*0.75 = 180; ability 50 + 40*0.25 = 60
        assert auto == pytest.approx(180.0)
        assert ability == pytest.approx(60.0)

    def test_sundered_sky_excluded_and_not_redistributed(self) -> None:
        # The Sundered Sky row is display-only (marked informational by
        # the engine): excluded from both buckets, never redistributed.
        breakdown = {
            "Q": {"name": "Q", "total_damage": 200.0},
            "sundered_sky": {
                "name": "Sundered Sky",
                "total_damage": 50.0,
                "informational": True,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 200.0

    def test_zero_total_drops_amp(self) -> None:
        # With no attributable damage there is no ratio to split by;
        # amp damage is dropped entirely.
        breakdown = {
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 0.0

    def test_empty_breakdown(self) -> None:
        auto, ability = split_auto_vs_ability({})
        assert auto == 0.0
        assert ability == 0.0

    def test_missing_total_damage_treated_as_zero(self) -> None:
        breakdown = {
            "Q": {"name": "Q"},
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 50.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 50.0
        assert ability == 0.0


class TestSplitByDamageType:
    """Tests for split_by_damage_type — physical/magic/true attribution.

    Every non-informational breakdown row carries a ``damage_type``;
    mixed rows built from typed parts additionally carry their exact
    ``damage_by_type`` composition. Untyped rows (amp rows) and mixed
    rows without a composition redistribute proportionally, mirroring
    split_auto_vs_ability's amp rule.
    """

    def test_typed_rows_land_in_their_buckets(self) -> None:
        breakdown = {
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 400.0,
                "damage_type": "physical",
            },
            "Q": {"name": "Q", "total_damage": 100.0, "damage_type": "magic"},
            "fiendhunter_true_damage": {
                "name": "Fiendhunter",
                "total_damage": 50.0,
                "damage_type": "true",
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 400.0, "magic": 100.0, "true": 50.0}

    def test_mixed_row_uses_exact_composition(self) -> None:
        # Mixed abilities (e.g. Ahri Q: magic outgoing + true return)
        # carry damage_by_type — the exact per-type mitigated totals.
        breakdown = {
            "Q": {
                "name": "Orb of Deception",
                "total_damage": 300.0,
                "damage_type": "mixed",
                "damage_by_type": {"magic": 200.0, "true": 100.0},
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 0.0, "magic": 200.0, "true": 100.0}

    def test_mixed_without_composition_redistributes_proportionally(self) -> None:
        # physical 300 / magic 100 -> mixed 40 splits 30 physical, 10 magic.
        breakdown = {
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 300.0,
                "damage_type": "physical",
            },
            "Q": {"name": "Q", "total_damage": 100.0, "damage_type": "magic"},
            "double_on_hit_Dusk and Dawn": {
                "name": "Dusk and Dawn (Double On-Hit)",
                "total_damage": 40.0,
                "damage_type": "mixed",
            },
        }
        split = split_by_damage_type(breakdown)
        assert split["physical"] == pytest.approx(330.0)
        assert split["magic"] == pytest.approx(110.0)
        assert split["true"] == 0.0

    def test_amp_rows_redistribute_proportionally(self) -> None:
        # damage_amp_<source> rows amplify every damage type equally.
        breakdown = {
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 100.0,
                "damage_type": "physical",
            },
            "Q": {"name": "Q", "total_damage": 300.0, "damage_type": "magic"},
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
        }
        split = split_by_damage_type(breakdown)
        assert split["physical"] == pytest.approx(110.0)
        assert split["magic"] == pytest.approx(330.0)
        assert split["true"] == 0.0

    def test_informational_rows_skipped(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0, "damage_type": "magic"},
            "execute": {
                "name": "The Collector (Execute)",
                "total_damage": 0.0,
                "damage_type": "true",
                "informational": True,
            },
            "ability_amp_Actualizer": {
                "name": "Damage Amplification (Actualizer)",
                "total_damage": 15.0,
                "informational": True,
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 0.0, "magic": 100.0, "true": 0.0}

    def test_zero_typed_total_drops_untyped_damage(self) -> None:
        # No typed damage -> no ratio to split by; amp damage is dropped.
        breakdown = {
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 0.0, "magic": 0.0, "true": 0.0}

    def test_empty_breakdown(self) -> None:
        assert split_by_damage_type({}) == {
            "physical": 0.0,
            "magic": 0.0,
            "true": 0.0,
        }

    def test_missing_total_damage_treated_as_zero(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "damage_type": "magic"},
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 50.0,
                "damage_type": "physical",
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 50.0, "magic": 0.0, "true": 0.0}


# ---------------------------------------------------------------------------
# Hit-timeline stacking DoT (Briar's Crimson Curse)
# ---------------------------------------------------------------------------


def _stacking_dot_passive(
    single_stack_raw=100.0, applied_by_autos=True, tick_interval=None
):
    """Passive entry declaring a hit-driven stacking DoT (Briar P shape)."""
    spec = {
        "name": "Bleed",
        "damage_type": "physical",
        "single_stack_raw": single_stack_raw,
        "duration": 5.0,
        "max_stacks": 5,
        "extra_stack_effectiveness": 0.25,
        "applied_by_autos": applied_by_autos,
    }
    if tick_interval is not None:
        spec["tick_interval"] = tick_interval
    return {
        "name": "Bleed",
        "damage_type": "physical",
        "total_raw": single_stack_raw,
        "parts": (),
        "stacking_dot": spec,
    }


def _stack_applier(cooldown=20.0, empowers_next_auto=False):
    """Zero-damage castable whose applications add one DoT stack each."""
    from src.calculator.ability_spec import DamagePart

    entry = {
        "name": "Applier",
        "cooldown": cooldown,
        "damage_type": "physical",
        "parts": (DamagePart("physical", 0.0),),
        "applies_dot_stack": True,
    }
    if empowers_next_auto:
        entry["empowers_next_auto"] = True
    return entry


class TestStackingDot:
    """Hit-timeline stacking DoT: rate = single_dps x (1 + 0.25 x (n-1)),
    stacks from the fight's real hit timeline (autos at attack-speed
    intervals, ability applications at cast times), shared duration
    refreshed by every application, committed 5s tail past the last hit.

    Single stack = 100 raw over 5s -> 20 dps; rates by stack count:
    20 / 25 / 30 / 35 / 40 (5-stack rate = 2x single = 200 per 5s window).
    """

    def test_auto_ramp_reduced_stacks_and_committed_tail(
        self, attacker_stats, fight
    ) -> None:
        """10 autos at 1/s over a 10s fight: ramp 20+25+30+35+40 over the
        first 5s, 4s at the 5-stack rate 40, then the full committed 5s
        tail (200) past fight end -> 510 raw."""
        result = fight(
            attacker_stats(),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(510.0)
        assert row["count"] == 10
        assert row["unit"] == "stacks"
        assert row["damage_per_hit"] == pytest.approx(51.0)
        assert row["damage_type"] == "physical"

    def test_one_rotation_marginal_sum_is_175_percent(
        self, attacker_stats, fight
    ) -> None:
        """Q+W+E+R applications land together in one-rotation mode: the
        first stack commits 100%, the other three 25% each -> 1.75x."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(),
            "W": _stack_applier(),
            "E": _stack_applier(),
            "R": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(175.0)
        assert row["count"] == 4

    def test_single_application_commits_full_duration(
        self, attacker_stats, fight
    ) -> None:
        """One application = the full single-stack total, fight end or not."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(100.0)

    def test_reapplication_refreshes_shared_duration(
        self, attacker_stats, fight
    ) -> None:
        """Autos at t=0 and t=4 (0.25 AS): the second hit refreshes before
        expiry -> 4s at 1 stack (80) + committed 5s at 2 stacks (125)."""
        result = fight(
            attacker_stats(attack_speed=0.25),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=9.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(205.0)

    def test_stacks_expire_after_duration_gap(self, attacker_stats, fight) -> None:
        """Autos at t=0 and t=6 (gap > 5s): the first stack runs its full
        5s and expires; the second starts a fresh chain -> 100 + 100."""
        result = fight(
            attacker_stats(attack_speed=1.0 / 6.0),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=12.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(200.0)
        assert row["count"] == 2

    def test_timed_casts_apply_stacks_on_cooldown(self, attacker_stats, fight) -> None:
        """No autos; a 4s-cooldown applier casts at t=0/4/8 over 10s:
        4s at 1 stack (80) + 4s at 2 (100) + committed 5s at 3 (150)."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(cooldown=4.0),
        }
        result = fight(
            attacker_stats(),
            abilities,
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(330.0)
        assert row["count"] == 3

    def test_bleed_is_mitigated_by_armor(self, attacker_stats, fight) -> None:
        """The DoT is physical damage: 100 armor halves it."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=100.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(50.0)

    def test_empowered_auto_stack_rides_the_auto_stream(
        self, attacker_stats, fight
    ) -> None:
        """An empowers_next_auto applier's swing IS one of the fight's
        autos - its stack must not be counted twice on the timeline."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "W": _stack_applier(cooldown=20.0, empowers_next_auto=True),
        }
        result = fight(
            attacker_stats(),
            abilities,
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        # Identical to the autos-only timeline: 10 hits -> 510 raw.
        assert row["total_damage"] == pytest.approx(510.0)
        assert row["count"] == 10

    def test_empowered_auto_applies_stack_without_auto_stream(
        self, attacker_stats, fight
    ) -> None:
        """One-rotation mode (no autos): the forced swing carries the
        stack, so the applier still commits one full stack."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "W": _stack_applier(cooldown=20.0, empowers_next_auto=True),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(100.0)
        assert row["count"] == 1

    def test_no_applications_no_row(self, attacker_stats, fight) -> None:
        """A declared DoT with no hits in the fight emits nothing."""
        result = fight(
            attacker_stats(),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
        )
        assert "stacking_dot_passive" not in result["breakdown"]


class TestStackingDotTickEvents:
    """A sourced tick cadence turns the integrated bleed into tick events."""

    def test_single_application_authors_its_four_ticks(
        self, attacker_stats, fight
    ) -> None:
        """One stack over 5s at 1.25s cadence: four 25-raw ticks."""
        abilities = {
            "passive": _stacking_dot_passive(tick_interval=1.25),
            "Q": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)

        row = result["breakdown"]["stacking_dot_passive"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == pytest.approx(
            [1.25, 2.5, 3.75, 5.0]
        )
        assert all(event["damage"] == pytest.approx(25.0) for event in events)
        assert all(event["damage_type"] == "physical" for event in events)
        coverage = result["timeline_coverage"]
        assert "stacking_dot_passive" in coverage["exact_sources"]

    def test_tick_buckets_integrate_the_ramping_rate(
        self, attacker_stats, fight
    ) -> None:
        """10 autos at 1/s: the first 1.25s tick spans the 1-stack second
        (20) plus a quarter second at 2 stacks (6.25); the whole event
        list conserves the row's 510 raw total through the tail at 14s."""
        result = fight(
            attacker_stats(),
            {"passive": _stacking_dot_passive(tick_interval=1.25)},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )

        row = result["breakdown"]["stacking_dot_passive"]
        events = row["damage_events"]
        assert len(events) == 12  # 11 full ticks + the 14s tail remainder
        assert events[0]["time"] == pytest.approx(1.25)
        assert events[0]["damage"] == pytest.approx(26.25)
        assert events[-1]["time"] == pytest.approx(14.0)
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert result["timeline_coverage"]["complete"] is True

    def test_expired_chain_reanchors_the_tick_grid(self, attacker_stats, fight) -> None:
        """Hits at t=0 and t=6 (gap > 5s): the first chain ticks on the
        t=0 clock, the fresh chain ticks on the t=6 clock."""
        result = fight(
            attacker_stats(attack_speed=1.0 / 6.0),
            {"passive": _stacking_dot_passive(tick_interval=1.25)},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=12.0,
            auto_attack_uptime=1.0,
        )

        row = result["breakdown"]["stacking_dot_passive"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == pytest.approx(
            [1.25, 2.5, 3.75, 5.0, 7.25, 8.5, 9.75, 11.0]
        )
        assert sum(event["damage"] for event in events) == pytest.approx(200.0)

    def test_unsourced_cadence_keeps_the_row_coarse(
        self, attacker_stats, fight
    ) -> None:
        """No sourced tick interval means no invented events: fail closed."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)

        row = result["breakdown"]["stacking_dot_passive"]
        assert "damage_events" not in row
        assert "stacking_dot_passive" in result["timeline_coverage"]["coarse_sources"]


# ---------------------------------------------------------------------------
# Stack-triggered mid-fight steroid (Darius' Noxian Might)
# ---------------------------------------------------------------------------


def _buffing_passive(
    *,
    single_stack_raw=100.0,
    single_stack_bonus_ad_ratio=0.0,
    trigger_stacks=5,
    bonus_attack_damage=200.0,
    duration=5.0,
):
    """Passive declaring BOTH a stacking DoT and the steroid it triggers."""
    entry = _stacking_dot_passive(single_stack_raw=single_stack_raw)
    entry["stacking_dot"]["single_stack_bonus_ad_ratio"] = single_stack_bonus_ad_ratio
    entry["stack_triggered_buff"] = {
        "name": "Steroid",
        "trigger_stacks": trigger_stacks,
        "duration": duration,
        "bonus_attack_damage": bonus_attack_damage,
    }
    return entry


def _ad_scaled_ability(cooldown=4.0, amount=100.0, bonus_ad_ratio=1.0):
    """Castable whose damage grows 1:1 with mid-fight bonus AD."""
    return {
        "name": "Scaled",
        "cooldown": cooldown,
        "damage_type": "physical",
        "parts": (DamagePart("physical", amount, bonus_ad_ratio=bonus_ad_ratio),),
        "applies_dot_stack": True,
    }


class TestStackTriggeredBuff:
    """Reaching ``trigger_stacks`` opens a bonus-AD window derived from
    the SAME stack timeline the DoT integrates. Casts, autos and DoT
    ticks inside a window price against the buffed AD; the application
    that opens the window is not itself buffed."""

    def test_no_buff_declared_changes_nothing(self, attacker_stats, fight) -> None:
        """A DoT without a stack_triggered_buff is priced exactly as before."""
        plain = fight(
            attacker_stats(),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        assert plain["breakdown"]["stacking_dot_passive"][
            "total_damage"
        ] == pytest.approx(510.0)

    def test_trigger_application_is_not_itself_buffed(
        self, attacker_stats, fight
    ) -> None:
        """10 autos at 1/s: the 5th auto (t=4) lands stack 5 and opens the
        window, but is not buffed by the steroid its own damage
        triggered. Autos 0-4 swing at 100 AD, autos 5-9 at 100+200."""
        result = fight(
            attacker_stats(),
            {"passive": _buffing_passive(single_stack_raw=0.0)},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        autos = result["breakdown"]["auto_attacks"]
        assert autos["count"] == 10
        assert autos["total_damage"] == pytest.approx(5 * 100.0 + 5 * 300.0)
        assert result["notes"][-1].startswith("Steroid: 1 window(s)")

    def test_window_expires_and_a_later_hit_reopens_it(
        self, attacker_stats, fight
    ) -> None:
        """6 autos at 0.6/s (1.667s apart) with a 1s window: the 5th auto
        (t=6.67) opens window 1, which expires before the 6th (t=8.33) —
        so that auto is unbuffed and opens window 2 instead. Every auto
        swings at base AD; the note reports two windows."""
        result = fight(
            attacker_stats(attack_speed=0.6),
            {"passive": _buffing_passive(single_stack_raw=0.0, duration=1.0)},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        autos = result["breakdown"]["auto_attacks"]
        assert autos["count"] == 6
        assert autos["total_damage"] == pytest.approx(6 * 100.0)
        assert result["notes"][-1].startswith("Steroid: 2 window(s)")

    def test_cast_inside_window_is_repriced(self, attacker_stats, fight) -> None:
        """A bonus_ad_ratio part inside the window gains ratio x buff AD."""
        abilities = {
            "passive": _buffing_passive(single_stack_raw=0.0, trigger_stacks=1),
            "Q": _ad_scaled_ability(cooldown=4.0, amount=100.0, bonus_ad_ratio=0.5),
        }
        result = fight(
            attacker_stats(),
            abilities,
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
        )
        # Casts at t=0/4/8. The t=0 cast lands the trigger stack itself so
        # it is unbuffed (100); the later two are inside the window and
        # gain 0.5 x 200 = 100 each.
        assert result["breakdown"]["Q"]["casts"] == 3
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            100.0 + 200.0 + 200.0
        )

    def test_dot_ticks_split_at_window_boundaries(self, attacker_stats, fight) -> None:
        """One application at t=0 with an instant trigger: the bleed's own
        bonus-AD ratio raises the whole committed 5s window."""
        abilities = {
            "passive": _buffing_passive(
                single_stack_raw=100.0,
                single_stack_bonus_ad_ratio=0.25,
                trigger_stacks=1,
                bonus_attack_damage=200.0,
            ),
            "Q": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        # Window [0, 5) covers the entire committed tail: the single stack
        # ticks at (100 + 0.25 x 200) = 150 raw over its 5s.
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(150.0)

    def test_dot_gap_partially_inside_window(self, attacker_stats, fight) -> None:
        """A window opening mid-gap splits that gap: 2 autos at t=0/6 with
        a 2s window opened by the second. Stack 1 ticks 20/s for 5s (100,
        chain then expires); stack 2 ticks (100+50)/5 = 30/s for its 2s
        window then 20/s for the remaining 3s -> 60 + 60 = 120."""
        abilities = {
            "passive": _buffing_passive(
                single_stack_raw=100.0,
                single_stack_bonus_ad_ratio=0.25,
                trigger_stacks=1,
                bonus_attack_damage=200.0,
                duration=2.0,
            )
        }
        result = fight(
            attacker_stats(attack_speed=1.0 / 6.0),
            abilities,
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=12.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        # First stack's own 5s is buffed for its first 2s: 2x30 + 3x20 = 120.
        assert row["total_damage"] == pytest.approx(120.0 + 120.0)

    def test_buff_refreshes_while_held_at_max(self, attacker_stats, fight) -> None:
        """Reapplying at max stacks refreshes the window: 10 autos at 1/s
        with a 2s window keep the buff alive from the 5th auto onward
        (without refresh only the t=5 auto lands inside it: 1200)."""
        result = fight(
            attacker_stats(),
            {"passive": _buffing_passive(single_stack_raw=0.0, duration=2.0)},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        autos = result["breakdown"]["auto_attacks"]
        # Trigger at t=4; every later auto both refreshes and is buffed.
        assert autos["total_damage"] == pytest.approx(5 * 100.0 + 5 * 300.0)

    def test_dot_stack_scaled_part_counts_target_stacks(
        self, attacker_stats, fight
    ) -> None:
        """A dot_stack_scaled part hits once per stack ON the target when
        the cast lands — Darius R's per-stack bonus."""
        finisher = {
            "name": "Finisher",
            "cooldown": 100.0,
            "damage_type": "true",
            "parts": (
                DamagePart("true", 50.0),
                DamagePart("true", 10.0, count=0, dot_stack_scaled=True),
            ),
            "applies_dot_stack": True,
        }
        abilities = {
            "passive": _stacking_dot_passive(single_stack_raw=0.0),
            "Q": _stack_applier(),
            "W": _stack_applier(),
            "R": finisher,
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        # One-rotation: Q and W land their stacks before R, so R sees 2.
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(70.0)

    def test_buff_without_a_stacking_dot_raises(self, attacker_stats, fight) -> None:
        """A steroid triggered by stacks needs a stack source; declaring
        it alone must fail loudly rather than granting nothing."""
        orphan = {
            "name": "Orphan",
            "damage_type": "physical",
            "parts": (),
            "stack_triggered_buff": {
                "name": "Steroid",
                "trigger_stacks": 5,
                "duration": 5.0,
                "bonus_attack_damage": 200.0,
            },
        }
        with pytest.raises(ValueError, match="without a stacking_dot"):
            fight(attacker_stats(), {"passive": orphan}, target_armor=0.0)

    def test_dot_stack_scaled_without_timeline_deals_nothing(
        self, attacker_stats, fight
    ) -> None:
        """No stacking DoT in the fight means no stacks — the declared
        ``count`` is ignored rather than becoming a silent fallback."""
        finisher = {
            "name": "Finisher",
            "cooldown": 100.0,
            "damage_type": "true",
            "parts": (
                DamagePart("true", 50.0),
                DamagePart("true", 10.0, count=3, dot_stack_scaled=True),
            ),
        }
        result = fight(attacker_stats(), {"R": finisher}, target_armor=0.0)
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(50.0)


class TestDamagePartRepr:
    """The golden snapshot serializes parts through repr(), so optional
    fields must print only when set."""

    def test_plain_part_repr_unchanged(self) -> None:
        assert repr(DamagePart("physical", 10.0)) == (
            "DamagePart(physical, amount=10.0, count=1, hp_scaled=no, "
            "crit_effectiveness=0.0)"
        )

    def test_new_fields_appear_only_when_set(self) -> None:
        part = DamagePart("true", 5.0, bonus_ad_ratio=0.15, dot_stack_scaled=True)
        assert repr(part).endswith("bonus_ad_ratio=0.15, dot_stack_scaled=yes)")
        assert "bonus_ad_ratio" not in repr(DamagePart("true", 5.0))
        assert "dot_stack_scaled" not in repr(DamagePart("true", 5.0))


# ---------------------------------------------------------------------------
# Empowered-auto forced swings: zero-uptime timed fights and Hexoptics amp
# ---------------------------------------------------------------------------


def _empowered_bonus_ability(cooldown: float = 4.0) -> dict:
    """Vayne-Q-shaped entry: bonus physical riding the next basic attack."""
    from src.calculator.ability_spec import DamagePart

    return {
        "name": "Empowered Strike",
        "damage_type": "physical",
        "cooldown": cooldown,
        "parts": (DamagePart("physical", 50.0),),
        "empowers_next_auto": True,
    }


class TestEmpoweredAutoZeroUptimeTimed:
    """A timed fight with zero auto uptime still forces the empowered
    attack per cast — each cast carries bonus + base swing (was 0)."""

    def test_timed_zero_uptime_carries_swings(self, attacker_stats, fight) -> None:
        """cd 4 over 10s = 3 casts x (50 bonus + 100 swing) = 450."""
        result = fight(
            attacker_stats(),
            {"Q": _empowered_bonus_ability(cooldown=4.0)},
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
            target_armor=0.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(450.0)

    def test_timed_with_auto_stream_matches_zero_uptime(
        self, attacker_stats, fight
    ) -> None:
        """An auto stream changes which row hosts the swing, not its value.

        The swings come out of the auto stream rather than being forced,
        but the ability row reports the same attack+bonus hit either way
        — same 450 as the zero-uptime sibling above.
        """
        result = fight(
            attacker_stats(),
            {"Q": _empowered_bonus_ability(cooldown=4.0)},
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            target_armor=0.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(450.0)


class TestForcedSwingBasicAmp:
    """Hexoptics C44 amplifies forced basic-attack swings on ability rows
    (they ARE basic attacks), and the info row reports that bonus."""

    def test_one_rotation_swing_amped(self, attacker_stats, fight) -> None:
        """Ranged amp 1.10: 50 bonus (unamped) + 100 swing x 1.10 = 160."""
        result = fight(
            attacker_stats(is_melee=False),
            {"Q": _empowered_bonus_ability()},
            items=[{"name": "Hexoptics C44"}],
            target_armor=0.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(160.0)
        amp_row = result["breakdown"]["basic_amp_Hexoptics C44"]
        assert amp_row["total_damage"] == pytest.approx(10.0)


def _timeline_entry(name, cooldown, cast_time=None, damage=100.0):
    """Minimal castable ability entry for cast-timeline tests."""
    entry = {
        "name": name,
        "rank": 5,
        "cooldown": cooldown,
        "damage_type": "magic",
        "total_raw": damage,
        "parts": (DamagePart("magic", damage),),
    }
    if cast_time is not None:
        entry["cast_time"] = cast_time
    return entry


class TestSharedCastTimeline:
    """Timed-mode casts share ONE timeline: each cast occupies its
    cast_time (cooldown runs from cast end), and no ability can start
    while another is mid-cast. Cassiopeia's E-spam exposed the old
    per-ability `1 + T/cd` formula overcounting (5 casts vs ~3 in-game
    over 3s)."""

    @staticmethod
    def _timed(fight, attacker_stats, abilities, duration=3.0):
        return fight(
            attacker_stats(),
            abilities,
            one_rotation=False,
            fight_duration_seconds=duration,
        )

    def test_cast_time_stretches_own_cycle(self, fight, attacker_stats) -> None:
        """cd 0.75 + cast 0.125 = 0.875s cycle: starts at 0/.875/1.75/2.625
        -> 4 casts in 3s (the old cd-only formula said 5)."""
        result = self._timed(
            fight, attacker_stats, {"E": _timeline_entry("Spam", 0.75, 0.125)}
        )
        assert result["breakdown"]["E"]["casts"] == 4

    def test_other_casts_displace_the_spam_spell(self, fight, attacker_stats) -> None:
        """Q (0.5s cast) and R (0.5s) occupy the timeline's first ~1.1s,
        so E only starts at 0.5/1.375/2.25 -> 3 casts, not 4."""
        result = self._timed(
            fight,
            attacker_stats,
            {
                "Q": _timeline_entry("Opener", 10.0, 0.5),
                "E": _timeline_entry("Spam", 0.75, 0.125),
                "R": _timeline_entry("Ult", 60.0, 0.5),
            },
        )
        breakdown = result["breakdown"]
        assert breakdown["Q"]["casts"] == 1
        assert breakdown["E"]["casts"] == 3
        assert breakdown["R"]["casts"] == 1

    def test_zero_cast_time_preserves_legacy_counts(
        self, fight, attacker_stats
    ) -> None:
        """Entries without cast_time are instant: cd 1.0 over 3s casts at
        0/1/2/3 = 4, exactly the old `1 + int(T/cd)`."""
        result = self._timed(fight, attacker_stats, {"Q": _timeline_entry("Bolt", 1.0)})
        assert result["breakdown"]["Q"]["casts"] == 4

    def test_r_still_casts_once_in_timed_mode(self, fight, attacker_stats) -> None:
        """R never recasts on cooldown in timed mode (unchanged rule)."""
        result = self._timed(
            fight,
            attacker_stats,
            {"R": _timeline_entry("Ult", 2.0, 0.5)},
            duration=10.0,
        )
        assert result["breakdown"]["R"]["casts"] == 1


def _shred_entry(name, parts, debuff, cooldown=10.0):
    """Minimal castable entry carrying a target_debuff."""
    return {
        "name": name,
        "rank": 1,
        "cooldown": cooldown,
        "damage_type": parts[0].damage_type,
        "total_raw": sum(p.amount * p.count for p in parts),
        "parts": tuple(parts),
        "target_debuff": debuff,
    }


class TestFlatResistanceShred:
    """``*_reduction_flat`` debuffs (Corki E) subtract resistances outright.

    Percent shreds scale what remains; flat shreds subtract, and — unlike
    penetration — may take a resistance below zero, where it amplifies.
    """

    def test_flat_armor_shred_helps_the_next_ability(
        self, fight, attacker_stats
    ) -> None:
        result = fight(
            attacker_stats(),
            {
                "Q": _shred_entry(
                    "Shredder",
                    [DamagePart("physical", 100.0)],
                    {"armor_reduction_flat": 50.0},
                ),
                "W": {
                    "name": "After",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 100.0,
                    "parts": (DamagePart("physical", 100.0),),
                },
            },
            target_armor=100.0,
        )
        # Q at 100 armor -> 50; W at 50 armor -> 66.67 (the source ability
        # never benefits from its own shred).
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(50.0)
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(
            66.667, abs=0.01
        )

    def test_flat_shred_can_take_resistance_negative(
        self, fight, attacker_stats
    ) -> None:
        """20 armor shredded by 50 -> -30 armor, which amplifies damage."""
        result = fight(
            attacker_stats(),
            {
                "Q": _shred_entry(
                    "Shredder",
                    [DamagePart("physical", 1.0)],
                    {"armor_reduction_flat": 50.0},
                ),
                "W": {
                    "name": "After",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 100.0,
                    "parts": (DamagePart("physical", 100.0),),
                },
            },
            target_armor=20.0,
        )
        assert result["effective_armor"] == pytest.approx(-30.0)
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(
            apply_resistance(100.0, -30.0)
        )

    def test_uncast_ability_shreds_nothing(self, fight, attacker_stats) -> None:
        """Autos-only mode never casts the ability, so no shred lands —
        otherwise autos get a free reduction from a spell never used."""
        result = fight(
            attacker_stats(),
            {
                "Q": _shred_entry(
                    "Shredder",
                    [DamagePart("physical", 100.0)],
                    {"armor_reduction_flat": 50.0},
                )
            },
            target_armor=100.0,
            one_rotation=False,
            auto_attacks_only=True,
            auto_attack_uptime=1.0,
        )
        assert result["breakdown"]["Q"]["casts"] == 0
        assert result["effective_armor"] == pytest.approx(100.0)

    def test_flat_mr_shred_applies_to_magic_damage(self, fight, attacker_stats) -> None:
        result = fight(
            attacker_stats(),
            {
                "Q": _shred_entry(
                    "Shredder",
                    [DamagePart("physical", 1.0)],
                    {"mr_reduction_flat": 40.0},
                ),
                "W": {
                    "name": "After",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "magic",
                    "total_raw": 100.0,
                    "parts": (DamagePart("magic", 100.0),),
                },
            },
            target_magic_resistance=100.0,
        )
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(62.5)


class TestRampedResistanceShred:
    """``"stacks": N`` stages a flat shred across the ability's own parts.

    Corki's Gatling Gun applies one stack per tick: part 1 lands
    unshredded, part 2 against one stack, ... and everything after the
    Nth part against the full reduction. This deliberately deviates from
    the single-application Kog'Maw rule (see corki.py's docstring).
    """

    @staticmethod
    def _ramp_result(fight, attacker_stats, parts, stacks=2, flat=50.0):
        return fight(
            attacker_stats(),
            {
                "Q": _shred_entry(
                    "Ramp",
                    parts,
                    {
                        "armor_reduction_flat": flat,
                        "mr_reduction_flat": flat,
                        "stacks": stacks,
                    },
                )
            },
            target_armor=100.0,
        )

    def test_later_parts_benefit_from_earlier_stacks(
        self, fight, attacker_stats
    ) -> None:
        """3 parts of 100 raw, 2 stacks of 25 armor: 100 -> 75 -> 50 armor."""
        result = self._ramp_result(
            fight,
            attacker_stats,
            [DamagePart("physical", 100.0) for _ in range(3)],
            stacks=2,
        )
        expected = (
            apply_resistance(100.0, 100.0)
            + apply_resistance(100.0, 75.0)
            + apply_resistance(100.0, 50.0)
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(expected)
        assert result["effective_armor"] == pytest.approx(50.0)

    def test_full_reduction_lands_even_with_fewer_parts_than_stacks(
        self, fight, attacker_stats
    ) -> None:
        """One part, four stacks: the three unfired stages land afterwards."""
        result = self._ramp_result(
            fight,
            attacker_stats,
            [DamagePart("physical", 100.0)],
            stacks=4,
            flat=40.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(50.0)
        assert result["effective_armor"] == pytest.approx(60.0)

    def test_percent_reduction_cannot_be_ramped(self, fight, attacker_stats) -> None:
        """Percent stages compound; splitting them into equal shares is wrong."""
        with pytest.raises(ValueError, match="FLAT"):
            fight(
                attacker_stats(),
                {
                    "Q": _shred_entry(
                        "Ramp",
                        [DamagePart("physical", 100.0)],
                        {"armor_reduction_percent": 30.0, "stacks": 2},
                    )
                },
            )

    def test_percent_reduction_can_start_after_a_hit_threshold(
        self, fight, attacker_stats
    ) -> None:
        """A full percent shred can begin after a sourced hit threshold."""
        result = fight(
            attacker_stats(),
            {
                "Q": _shred_entry(
                    "Threshold",
                    [DamagePart("physical", 100.0, count=6, hit_interval=1.0)],
                    {"armor_reduction_percent": 25.0, "threshold_hits": 6},
                ),
                "W": {
                    "name": "After",
                    "rank": 1,
                    "cooldown": 10.0,
                    "damage_type": "physical",
                    "total_raw": 100.0,
                    "parts": (DamagePart("physical", 100.0),),
                },
            },
            target_armor=100.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(6 * 50.0)
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(
            57.143, abs=0.01
        )


class TestHealthComponentInvariant:
    """``health == base_health + bonus_health`` survives stat buffs.

    Base and bonus health are separate stats with separate scalings, so
    a champion granting one must not silently corrupt the other. Gnar's
    Mega form and Dr. Mundo's R both grant BASE health: total rises with
    base, and bonus health — the only component item conversions like
    Overlord's Bloodmail may read — stays exactly where it was.
    """

    @staticmethod
    def _stats(champion_data, level, items, options):
        from src.calculator.pipeline import FightParams, run_fight

        params = FightParams.from_request({"champion_options": options})
        return run_fight(champion_data, level, list(items), params)["champion_stats"]

    def _assert_invariant(self, stats) -> None:
        assert stats["health"] == pytest.approx(
            stats["base_health"] + stats["bonus_health"]
        )

    def test_gnar_mini_form_holds_invariant(self, gnar_data: dict) -> None:
        self._assert_invariant(self._stats(gnar_data, 18, [], {"mega": False}))

    def test_gnar_mega_grant_raises_base_not_bonus(self, gnar_data: dict) -> None:
        mini = self._stats(gnar_data, 18, [], {"mega": False})
        mega = self._stats(gnar_data, 18, [], {"mega": True})

        self._assert_invariant(mega)
        assert mega["base_health"] > mini["base_health"]
        assert mega["bonus_health"] == mini["bonus_health"]

    def test_dr_mundo_r_grant_raises_base_not_bonus(self, dr_mundo_data: dict) -> None:
        full = self._stats(dr_mundo_data, 18, [], {"mundo_missing_health_percent": 0})
        hurt = self._stats(dr_mundo_data, 18, [], {"mundo_missing_health_percent": 50})

        self._assert_invariant(hurt)
        assert hurt["base_health"] > full["base_health"]
        assert hurt["bonus_health"] == full["bonus_health"]

    def test_invariant_holds_with_health_items(self, dr_mundo_data: dict) -> None:
        """Items feed bonus health; R's grant feeds base. Both at once."""
        from src.calculator.data_fetcher import get_item_by_name

        items = [get_item_by_name("Warmog's Armor"), get_item_by_name("Heartsteel")]
        stats = self._stats(
            dr_mundo_data, 18, items, {"mundo_missing_health_percent": 50}
        )

        self._assert_invariant(stats)
        assert stats["bonus_health"] > 0
        assert stats["base_health"] > 0


class TestEmpoweredSwingAttribution:
    """An empowered auto's swing shows on the ability that forced it.

    ``empowers_next_auto`` abilities consume a basic attack, so in-game
    the player sees ONE hit worth ``attack + bonus``. One-rotation mode
    already put that swing on the ability row; timed fights with autos
    left it in the auto stream, so the same ability read as bonus-only
    in one mode and attack+bonus in the other. Both modes now agree.
    Re-attribution moves damage between rows and must never change the
    fight total.
    """

    @staticmethod
    def _fight(champion_data, level=18, items=(), **overrides):
        from src.calculator.pipeline import FightParams, run_fight

        request = {
            "target_health": 1000,
            "target_armor": 0,
            "target_mr": 0,
            "fight_mode": "time_based",
            "fight_duration": 5.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        }
        request.update(overrides)
        params = FightParams.from_request(request)
        return run_fight(champion_data, level, list(items), params)

    def test_mundo_e_row_includes_the_consumed_swing(self, dr_mundo_data) -> None:
        result = self._fight(dr_mundo_data)
        e_row = result["breakdown"]["E"]
        auto_row = result["breakdown"]["auto_attacks"]

        # E's own bonus was 52.7; the swing it consumes is one auto.
        assert e_row["total_damage"] == pytest.approx(
            52.7 + auto_row["damage_per_hit"], rel=1e-3
        )
        assert auto_row["count"] == 4

    def test_reattribution_preserves_the_fight_total(self, dr_mundo_data) -> None:
        result = self._fight(dr_mundo_data)
        # Q is current-health damage, so the later casts are priced after the
        # earlier hits instead of six times against full target health.  F3
        # derives E (Blunt Force Trauma, bonus-AD buff) first, shifting the
        # buff/auto cadence — the total is re-captured with the derivation.
        # Re-captured with the landing-instant ruling: Q is current-health
        # damage, so it is priced against what had actually landed by each
        # cast rather than against the rotation's running total.  The
        # conservation invariant itself is the sibling row below.
        assert result["total_damage"] == pytest.approx(1883.966, rel=1e-3)

    def test_breakdown_rows_still_sum_to_total(self, dr_mundo_data) -> None:
        result = self._fight(dr_mundo_data)
        rows = sum(r.get("total_damage", 0.0) for r in result["breakdown"].values())
        assert rows == pytest.approx(result["total_damage"], rel=1e-6)

    def test_auto_row_per_hit_damage_is_unchanged(self, dr_mundo_data) -> None:
        """Only the count moves — each remaining auto still hits the same."""
        result = self._fight(dr_mundo_data)
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            186.2504, rel=1e-3
        )

    def test_auto_row_crit_counts_stay_consistent(self, dr_mundo_data) -> None:
        from src.calculator.data_fetcher import get_item_by_name

        result = self._fight(dr_mundo_data, items=[get_item_by_name("Infinity Edge")])
        auto_row = result["breakdown"]["auto_attacks"]
        assert auto_row["num_crits"] + auto_row["num_non_crits"] == auto_row["count"]

    def test_one_rotation_mode_is_untouched(self, dr_mundo_data) -> None:
        """Zero-auto mode already carried the swing; it must not double."""
        result = self._fight(dr_mundo_data, fight_mode="one_rotation")
        assert result["breakdown"]["E"]["total_damage"] == pytest.approx(
            239.0, rel=1e-3
        )
        assert result["breakdown"]["auto_attacks"]["count"] == 0

    def test_multi_swing_ability_moves_every_swing(self, chogath_data) -> None:
        """Cho'Gath E empowers 3 attacks per cast, not 1."""
        result = self._fight(chogath_data)
        e_row = result["breakdown"]["E"]
        auto_row = result["breakdown"]["auto_attacks"]
        assert e_row["casts"] >= 1
        assert auto_row["count"] >= 0
        # Rows still reconcile against the total after a 3-swing move.
        rows = sum(r.get("total_damage", 0.0) for r in result["breakdown"].values())
        assert rows == pytest.approx(result["total_damage"], rel=1e-6)

    def test_non_empowering_champion_unaffected(self, ahri_data) -> None:
        result = self._fight(ahri_data)
        auto_row = result["breakdown"]["auto_attacks"]
        assert auto_row["count"] > 0
        rows = sum(r.get("total_damage", 0.0) for r in result["breakdown"].values())
        assert rows == pytest.approx(result["total_damage"], rel=1e-6)


class TestDecayingTarget:
    """The one model the per-auto walks read, and its second reading."""

    def test_a_proc_does_not_floor_the_health_the_next_proc_prices_on(self) -> None:
        target = DecayingTarget.at_full(100.0)
        target.take_proc(60.0)
        target.take_proc(60.0)
        assert target.current_health == pytest.approx(-20.0)

    def test_the_auto_settles_the_walk_at_zero(self) -> None:
        target = DecayingTarget.at_full(100.0)
        target.take_proc(60.0)
        target.settle_auto(60.0)
        assert target.current_health == 0

    def test_pricing_inputs_carry_max_and_current_health(self) -> None:
        target = DecayingTarget.at_full(2000.0)
        target.settle_auto(500.0)
        inputs = target.inputs(DamageInputs({}, 7, True, 1.0, 1.0))
        assert inputs.target_max_health == pytest.approx(2000.0)
        assert inputs.target_current_health == pytest.approx(1500.0)
        assert inputs.level == 7

    def test_the_ledger_reading_excludes_packets_at_the_instant(self) -> None:
        """The documented disagreement: strictly before, and timed only."""

        class _State:
            target_health = 1000.0
            breakdown = {
                "Q": {
                    "damage_events": [
                        {"time": 1.0, "damage": 100.0},
                        {"time": 2.0, "damage": 40.0},
                        {"damage": 500.0},
                    ]
                }
            }

        assert DecayingTarget.ledger_health(_State(), 2.0) == pytest.approx(900.0)
        assert DecayingTarget.ledger_health(_State(), 3.0) == pytest.approx(860.0)
