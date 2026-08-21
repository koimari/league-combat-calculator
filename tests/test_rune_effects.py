"""Tests for keystone rune resolution and every compiled keystone's formula.

Every number a compiler produces is asserted against the value read live
out of ``rune_effects.RUNE_EFFECTS`` (parsed from ``data/runes.json``),
never against a number typed here, and every required key is deleted in
turn to prove the compiler raises instead of falling back — CLAUDE.md rule
5 for runes, as evidence rather than as a claim.
"""

import pytest

from src.calculator import rune_effects
from src.calculator.ability_spec import Disposition
from src.calculator.item_effects import DamageInputs


def _inputs(level=1, bonus_ad=0.0, ap=0.0, is_melee=False, **stats):
    return DamageInputs(
        champion_stats={
            "bonus_attack_damage": bonus_ad,
            "ability_power": ap,
            **stats,
        },
        level=level,
        is_melee=is_melee,
        target_max_health=1000.0,
        target_current_health=1000.0,
    )


def _cached(name):
    """The rune's cached ``effects`` block — the test's only source of numbers."""
    return rune_effects.RUNE_EFFECTS[name]["effects"]


def _without(name, key):
    """The whole registry with one key dropped from one rune's effects."""
    return {
        rune: (
            {
                **entry,
                "effects": {k: v for k, v in entry["effects"].items() if k != key},
            }
            if rune == name
            else entry
        )
        for rune, entry in rune_effects.RUNE_EFFECTS.items()
    }


class TestResolveKeystone:
    def test_empty_selection_resolves_to_none(self):
        assert rune_effects.resolve_rune("") is None

    def test_unknown_keystone_raises(self):
        with pytest.raises(ValueError, match="Fake Rune"):
            rune_effects.resolve_rune("Fake Rune")

    def test_every_cached_keystone_has_a_compiler(self):
        keystones = {
            name
            for name, entry in rune_effects.RUNE_EFFECTS.items()
            if entry.get("row") == 0
        }
        assert set(rune_effects._KEYSTONE_COMPILERS) == keystones

    def test_a_keystone_with_no_compiler_still_fails_closed(self, monkeypatch):
        """The withhold survives its own population emptying.

        All 17 cached keystones compile, so the fail-closed path is proven
        on a synthetic rune instead of being deleted with its last user.
        """
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS, "Synthetic Keystone", {"name": "Synthetic"}
        )
        with pytest.raises(ValueError, match="not modeled"):
            rune_effects.resolve_rune("Synthetic Keystone")

    def test_electrocute_resolves(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert effect.rune_name == "Electrocute"
        assert effect.stacks_required == 3
        assert effect.stack_window_seconds == 3.0
        assert effect.cooldown_seconds == 20.0
        assert effect.proc_delay_seconds == 0.25


class TestElectrocuteFormula:
    def test_base_damage_by_level(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(70.0)
        assert effect.raw_damage(_inputs(level=11)) == pytest.approx(170.0)
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(260.0)

    def test_ratio_scaling(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert effect.raw_damage(_inputs(level=1, bonus_ad=100.0)) == pytest.approx(
            80.0
        )
        assert effect.raw_damage(_inputs(level=1, ap=200.0)) == pytest.approx(80.0)

    def test_adaptive_type_prefers_larger_contribution(self):
        effect = rune_effects.resolve_rune("Electrocute")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 100.0}
        magic = {"bonus_attack_damage": 40.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"  # 10 AD > 5 AP contribution
        assert effect.damage_type(magic) == "magic"  # 4 < 5

    def test_adaptive_type_defaults_to_magic_on_tie_or_zero(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert (
            effect.damage_type({"bonus_attack_damage": 0.0, "ability_power": 0.0})
            == "magic"
        )
        tie = {"bonus_attack_damage": 50.0, "ability_power": 100.0}  # 5 == 5
        assert effect.damage_type(tie) == "magic"

    def test_missing_registry_key_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v for k, v in entry["effects"].items() if k != "ap_ratio"
                    },
                }
                if name == "Electrocute"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Electrocute.*ap_ratio"):
            rune_effects.resolve_rune("Electrocute")


class TestFirstStrike:
    def test_first_strike_resolves_to_window_amp_effect(self):
        effect = rune_effects.resolve_rune("First Strike")
        assert isinstance(effect, rune_effects.RuneWindowAmpEffect)
        assert effect.rune_name == "First Strike"
        assert effect.breakdown_key == "keystone_First Strike"
        assert effect.activation_gold == 10.0

    def test_the_window_and_the_ratio_live_in_the_declaration(self):
        """One number, one home: the amp chain slot owns both (3.2)."""
        from src.calculator.interpreters import (  # pylint: disable=import-outside-toplevel
            delta_amp,
        )
        from src.calculator.item_behavior import (  # pylint: disable=import-outside-toplevel
            AmpChainSlot,
        )

        slot = delta_amp.resolve_slot(
            ["First Strike"],
            AmpChainSlot.OPENING_WINDOW,
            level=18,
            fight_duration_seconds=10.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        assert slot is not None
        assert slot.window() == (0.0, 3.0)
        assert slot.fractions[0] == pytest.approx(0.07)
        assert slot.uniform_bonus_damage_type() == "true"

    def test_gold_conversion_is_melee_ranged_split(self):
        effect = rune_effects.resolve_rune("First Strike")
        assert effect.gold_conversion(is_melee=True) == pytest.approx(0.50)
        assert effect.gold_conversion(is_melee=False) == pytest.approx(0.35)

    def test_missing_registry_key_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "gold_conversion_ratios"
                    },
                }
                if name == "First Strike"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="First Strike.*gold_conversion_ratios"):
            rune_effects.resolve_rune("First Strike")


class TestPressTheAttack:
    def test_press_the_attack_resolves_to_proc_amp_effect(self):
        effect = rune_effects.resolve_rune("Press the Attack")
        assert isinstance(effect, rune_effects.RuneProcAmpEffect)
        assert effect.rune_name == "Press the Attack"
        assert effect.breakdown_key == "keystone_Press the Attack"
        assert effect.amp_breakdown_key == "keystone_Press the Attack amp"
        assert effect.amp_display_name == "Press the Attack amp (keystone)"
        assert effect.stacks_required == 3
        assert effect.stack_duration_seconds == 4.0
        assert effect.cooldown_seconds == 6.0

    def test_the_lasting_amp_lives_in_the_declaration(self):
        """One number, one home: the amp chain slot owns the ratio (3.2)."""
        from src.calculator.interpreters import (  # pylint: disable=import-outside-toplevel
            delta_amp,
        )
        from src.calculator.item_behavior import (  # pylint: disable=import-outside-toplevel
            AmpChainSlot,
        )

        slot = delta_amp.resolve_slot(
            ["Press the Attack"],
            AmpChainSlot.LASTING_PROC_AMP,
            level=18,
            fight_duration_seconds=10.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        assert slot is not None
        assert slot.fractions[0] == pytest.approx(0.08)
        # The triggering swing lands the instant the buff turns on, so it is
        # outside a strict after-trigger activation.
        assert not slot.applies_after(2.0, 2.0)
        assert slot.applies_after(2.5, 2.0)
        assert slot.prices_damage_type("magic")
        assert not slot.prices_damage_type("true")

    def test_proc_damage_by_level_has_no_ratio_scaling(self):
        effect = rune_effects.resolve_rune("Press the Attack")
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(40.0)
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(160.0)
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(174.117647)
        # The proc is pure leveled adaptive damage — stats must not move it.
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=300.0, ap=500.0)
        ) == pytest.approx(160.0)

    def test_adaptive_type_compares_bonus_ad_against_ap(self):
        effect = rune_effects.resolve_rune("Press the Attack")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 50.0}
        magic = {"bonus_attack_damage": 50.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"
        assert effect.damage_type(magic) == "magic"

    def test_adaptive_type_defaults_to_magic_on_tie_or_zero(self):
        # Ties follow the champion's adaptive type in game; the engine
        # carries no adaptive type, so it defaults magic like Electrocute.
        effect = rune_effects.resolve_rune("Press the Attack")
        assert (
            effect.damage_type({"bonus_attack_damage": 0.0, "ability_power": 0.0})
            == "magic"
        )

    def test_missing_registry_key_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "stack_duration_seconds"
                    },
                }
                if name == "Press the Attack"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Press the Attack.*stack_duration_seconds"):
            rune_effects.resolve_rune("Press the Attack")

    def test_a_missing_amp_ratio_raises_through_the_reference(self, monkeypatch):
        """Rule 5 reaches keystones: the declaration's read fails loud too."""
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "damage_amp_ratio"
                    },
                }
                if name == "Press the Attack"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        from src.calculator.value_ref import (  # pylint: disable=import-outside-toplevel
            ValueRef,
        )

        with pytest.raises(KeyError, match="Press the Attack.*damage_amp_ratio"):
            ValueRef("RUNE_EFFECTS", "Press the Attack", "damage_amp_ratio").get()


class TestArcaneComet:
    def test_arcane_comet_resolves_to_ability_proc_effect(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        assert isinstance(effect, rune_effects.RuneAbilityProcEffect)
        assert effect.rune_name == "Arcane Comet"
        assert effect.breakdown_key == "keystone_Arcane Comet"
        assert effect.proc_delay_seconds == pytest.approx(0.8)
        assert effect.assumed_travel_distance == 375.0
        # 375 of the 750-unit span → halfway up the 0-100% damage table.
        assert effect.distance_amp_ratio == pytest.approx(0.5)

    def test_cooldown_scales_with_level(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        assert effect.cooldown_at(1) == pytest.approx(20.0)
        assert effect.cooldown_at(18) == pytest.approx(8.0)
        assert effect.cooldown_at(20) == pytest.approx(20 - 12 / 17 * 19)
        # Out-of-range levels clamp like the leveling arrays do.
        assert effect.cooldown_at(0) == pytest.approx(20.0)
        assert effect.cooldown_at(30) == pytest.approx(20 - 12 / 17 * 19)

    def test_damage_is_min_formula_amped_by_assumed_distance(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        # (15 base at level 1) × 1.5 distance amp
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(22.5)
        # (100 base at level 18) × 1.5
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(150.0)
        # (110 base at level 20) × 1.5 — meets the wiki's max-range 220
        # array exactly at the 100%-amp endpoint, halved at ours.
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(165.0)

    def test_ratios_are_amped_with_the_base(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        # (15 + 10% × 100 bonus AD) × 1.5
        assert effect.raw_damage(_inputs(level=1, bonus_ad=100.0)) == pytest.approx(
            37.5
        )
        # (15 + 5% × 200 AP) × 1.5
        assert effect.raw_damage(_inputs(level=1, ap=200.0)) == pytest.approx(37.5)

    def test_adaptive_type_prefers_larger_contribution(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 100.0}
        magic = {"bonus_attack_damage": 40.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"  # 10 > 5
        assert effect.damage_type(magic) == "magic"  # 4 < 5
        assert (
            effect.damage_type({"bonus_attack_damage": 0.0, "ability_power": 0.0})
            == "magic"
        )

    def test_missing_distance_scaling_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "distance_scaling"
                    },
                }
                if name == "Arcane Comet"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*distance_scaling"):
            rune_effects.resolve_rune("Arcane Comet")

    def test_swapped_leveling_tables_raise_with_context(self, monkeypatch):
        # The compiler picks leveling[0] as the minimum-damage table by
        # sentence order. A reworded wiki description leading with the
        # max-range table would silently double every comet — certify
        # that max = min × (1 + full amp) or fail closed.
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        **entry["effects"],
                        "leveling": list(reversed(entry["effects"]["leveling"])),
                    },
                }
                if name == "Arcane Comet"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*leveling"):
            rune_effects.resolve_rune("Arcane Comet")

    def test_degenerate_distance_span_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        **entry["effects"],
                        "distance_scaling": {
                            "values": [0.0, 100.0],
                            "distance_range": [750.0, 750.0],
                        },
                    },
                }
                if name == "Arcane Comet"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*distance_scaling"):
            rune_effects.resolve_rune("Arcane Comet")

    def test_scalar_cooldown_raises_with_context(self, monkeypatch):
        # A wiki edit that flattens the cooldown to one number must fail
        # closed — a flat 20s cooldown would understate every level-up.
        broken = {
            name: ({**entry, "cooldown": 20.0} if name == "Arcane Comet" else entry)
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*cooldown"):
            rune_effects.resolve_rune("Arcane Comet")


class TestSummonAery:
    def test_aery_resolves_to_an_instance_stream_proc(self):
        effect = rune_effects.resolve_rune("Summon Aery")
        assert isinstance(effect, rune_effects.RuneProcEffect)
        assert effect.trigger is rune_effects.RuneTrigger.DAMAGE_INSTANCES
        assert effect.stacks_required == 1
        assert effect.stack_window_seconds is None

    def test_damage_is_the_cached_leveling_and_ratios(self):
        effect = rune_effects.resolve_rune("Summon Aery")
        cached = _cached("Summon Aery")
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(
            cached["leveling"][0][17]
        )
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=100.0, ap=200.0)
        ) == pytest.approx(
            cached["leveling"][0][17]
            + cached["bonus_ad_ratio"] * 100.0
            + cached["ap_ratio"] * 200.0
        )

    def test_the_round_trip_is_the_cached_pounce_plus_the_declared_return(self):
        effect = rune_effects.resolve_rune("Summon Aery")
        pounce = _cached("Summon Aery")["proc_delay_seconds"]
        assert effect.proc_delay_seconds == pytest.approx(pounce)
        assert effect.cooldown_seconds == pytest.approx(
            pounce + rune_effects.SUMMON_AERY_ASSUMED_RETURN_SECONDS
        )

    def test_the_assumed_round_trip_and_the_withheld_shield_are_disclosed(self):
        effect = rune_effects.resolve_rune("Summon Aery")
        assert any("assumed" in note for note in effect.disclosures)
        assert any(
            "shield is withheld" in note for note in effect.disclosures
        ), effect.disclosures

    def test_swapped_leveling_tables_raise_with_context(self, monkeypatch):
        # Damage is leveling[0] by sentence order; a reworded page leading
        # with the ally shield would double every pounce.
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        **entry["effects"],
                        "leveling": list(reversed(entry["effects"]["leveling"])),
                    },
                }
                if name == "Summon Aery"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Summon Aery.*leveling"):
            rune_effects.resolve_rune("Summon Aery")


class TestHailOfBlades:
    def test_hail_of_blades_is_a_basic_attack_proc_on_its_cached_cooldown(self):
        effect = rune_effects.resolve_rune("Hail of Blades")
        assert effect.trigger is rune_effects.RuneTrigger.BASIC_ATTACKS
        assert effect.cooldown_seconds == pytest.approx(
            rune_effects.RUNE_EFFECTS["Hail of Blades"]["cooldown"]
        )
        assert effect.stacks_required == 1

    def test_damage_is_true_and_reads_the_cached_leveling_and_ratios(self):
        effect = rune_effects.resolve_rune("Hail of Blades")
        cached = _cached("Hail of Blades")
        assert effect.damage_type({"bonus_attack_damage": 500.0}) == "true"
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=100.0, ap=100.0)
        ) == pytest.approx(
            cached["leveling"][0][17]
            + cached["bonus_ad_ratio"] * 100.0
            + cached["ap_ratio"] * 100.0
        )

    def test_the_attack_speed_half_is_withheld_in_the_cached_words(self):
        effect = rune_effects.resolve_rune("Hail of Blades")
        melee, ranged = _cached("Hail of Blades")["attack_speed_ratios"]
        withheld = next(note for note in effect.disclosures if "withheld" in note)
        assert f"{melee * 100:g}%" in withheld and f"{ranged * 100:g}%" in withheld

    def test_a_scalar_cooldown_still_reads(self):
        # Top-level, not in ``effects``: prove the accessor reads the entry.
        assert rune_effects.rune_effect_value("Hail of Blades", "cooldown") == 10.0

    def test_its_priced_numbers_are_pinned_to_the_patch_they_came_from(self):
        """A tripwire for the re-pull, not a second source.

        Every other test here reads the cache, so a wiki rebalance moves the
        answer with nothing saying so — 16.16 moved all four of these at
        once (base 4 -> 2, bonus AD 8% -> 12%, AP 6% -> 10%, attack speed
        120% -> 90%) and no test noticed. Re-pin these on patch day, with
        the change explained, exactly as the golden baseline is re-captured.
        """
        cached = _cached("Hail of Blades")
        assert cached["leveling"][0][0] == pytest.approx(2.0)
        assert cached["leveling"][0][17] == pytest.approx(20.0)
        assert cached["bonus_ad_ratio"] == pytest.approx(0.12)
        assert cached["ap_ratio"] == pytest.approx(0.10)
        assert cached["attack_speed_ratios"] == [0.9, 0.6]


class TestGraspOfTheUndying:
    def test_damage_is_the_cached_share_of_the_holders_maximum_health(self):
        effect = rune_effects.resolve_rune("Grasp of the Undying")
        melee_ratio, ranged_ratio = _cached("Grasp of the Undying")[
            "max_health_damage_ratios"
        ]
        assert effect.raw_damage(
            _inputs(is_melee=True, health=2000.0)
        ) == pytest.approx(melee_ratio * 2000.0)
        assert effect.raw_damage(
            _inputs(is_melee=False, health=2000.0)
        ) == pytest.approx(ranged_ratio * 2000.0)
        assert effect.damage_type({"bonus_attack_damage": 500.0}) == "magic"

    def test_exactly_one_proc_is_priced_and_the_reason_is_published(self):
        effect = rune_effects.resolve_rune("Grasp of the Undying")
        assert effect.cooldown_seconds == float("inf")
        assert any("floor of one" in note for note in effect.disclosures)

    def test_the_heal_and_permanent_health_are_withheld(self):
        effect = rune_effects.resolve_rune("Grasp of the Undying")
        assert any("heal" in note and "withheld" in note for note in effect.disclosures)


class TestLethalTempo:
    def test_the_bolt_starts_one_swing_past_the_cached_maximum_stacks(self):
        effect = rune_effects.resolve_rune("Lethal Tempo")
        assert effect.stacks_required == _cached("Lethal Tempo")["max_stacks"] + 1
        assert effect.consumes_stacks is False
        assert effect.trigger is rune_effects.RuneTrigger.BASIC_ATTACKS

    def test_damage_reads_the_cached_melee_and_ranged_tables(self):
        effect = rune_effects.resolve_rune("Lethal Tempo")
        melee, ranged = _cached("Lethal Tempo")["melee_ranged_leveling"]
        assert effect.raw_damage(_inputs(level=18, is_melee=True)) == pytest.approx(
            melee[17]
        )
        assert effect.raw_damage(_inputs(level=18, is_melee=False)) == pytest.approx(
            ranged[17]
        )

    def test_the_bolt_grows_with_the_builds_bonus_attack_speed(self):
        effect = rune_effects.resolve_rune("Lethal Tempo")
        cached = _cached("Lethal Tempo")
        melee_per_as = cached["damage_per_bonus_attack_speed_ratios"][0]
        melee_base = cached["melee_ranged_leveling"][0][17]
        assert effect.raw_damage(
            _inputs(level=18, is_melee=True, bonus_attack_speed=50.0)
        ) == pytest.approx(melee_base * (1.0 + melee_per_as * 50.0))

    def test_the_attack_speed_half_is_withheld(self):
        effect = rune_effects.resolve_rune("Lethal Tempo")
        assert any(
            "attack speed" in note and "withheld" in note for note in effect.disclosures
        )


class TestDeathfireTouch:
    def test_one_tick_per_damaging_cast_at_the_cached_cadence(self):
        effect = rune_effects.resolve_rune("Deathfire Touch")
        cached = _cached("Deathfire Touch")
        assert effect.trigger is rune_effects.RuneTrigger.DAMAGING_CASTS
        assert effect.cooldown_seconds == 0.0
        assert effect.proc_delay_seconds == pytest.approx(
            cached["tick_interval_seconds"]
        )

    def test_the_tick_reads_the_base_table_and_the_cached_ratios(self):
        effect = rune_effects.resolve_rune("Deathfire Touch")
        cached = _cached("Deathfire Touch")
        assert effect.damage_type({"bonus_attack_damage": 500.0}) == "magic"
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=100.0, ap=100.0)
        ) == pytest.approx(
            cached["leveling"][0][17]
            + cached["bonus_ad_ratio"] * 100.0
            + cached["ap_ratio"] * 100.0
        )

    def test_the_withheld_duration_and_escalation_are_disclosed(self):
        effect = rune_effects.resolve_rune("Deathfire Touch")
        assert any("floor of one per cast" in note for note in effect.disclosures)

    def test_swapped_leveling_tables_raise_with_context(self, monkeypatch):
        # leveling[1] is leveling[0] escalated; leading with it would
        # overstate every tick by the escalation.
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        **entry["effects"],
                        "leveling": list(reversed(entry["effects"]["leveling"])),
                    },
                }
                if name == "Deathfire Touch"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Deathfire Touch.*leveling"):
            rune_effects.resolve_rune("Deathfire Touch")


# Every key each new compiler reads out of the rune's ``effects`` block.
# Deleting one must raise, naming the rune and the key: rule 5's "no literal
# fallbacks" is only a claim until every read is proven to have no fallback.
_COMPILED_KEYS = {
    "Summon Aery": ("leveling", "bonus_ad_ratio", "ap_ratio", "proc_delay_seconds"),
    "Hail of Blades": ("leveling", "bonus_ad_ratio", "ap_ratio", "attack_speed_ratios"),
    "Grasp of the Undying": (
        "max_health_damage_ratios",
        "max_health_heal_ratios",
        "permanent_bonus_health",
    ),
    "Lethal Tempo": (
        "melee_ranged_leveling",
        "damage_per_bonus_attack_speed_ratios",
        "attack_speed_ratios",
        "max_stacks",
    ),
    "Deathfire Touch": (
        "leveling",
        "bonus_ad_ratio",
        "ap_ratio",
        "tick_interval_seconds",
    ),
}


@pytest.mark.parametrize(
    "name,key",
    [(name, key) for name, keys in _COMPILED_KEYS.items() for key in keys],
)
def test_every_compiled_number_fails_loud_when_the_cache_loses_it(
    monkeypatch, name, key
):
    monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", _without(name, key))
    with pytest.raises(KeyError, match=f"{name}.*{key}"):
        rune_effects.resolve_rune(name)


def test_hail_of_blades_fails_loud_without_its_top_level_cooldown(monkeypatch):
    broken = {
        name: (
            {k: v for k, v in entry.items() if k != "cooldown"}
            if name == "Hail of Blades"
            else entry
        )
        for name, entry in rune_effects.RUNE_EFFECTS.items()
    }
    monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
    with pytest.raises(KeyError, match="Hail of Blades.*cooldown"):
        rune_effects.resolve_rune("Hail of Blades")


class TestKeystonesThatBookNoDamage:
    """The eight keystones that price nothing, and the two reasons why.

    ``STRUCTURAL_ZERO`` is "zero is the answer"; ``WITHHELD`` is "the number
    exists and this engine has no channel for it". Both are compiled and
    selectable — a keystone that refuses is the failure being removed — and
    both publish their receipt.
    """

    @pytest.mark.parametrize(
        "name",
        ["Unsealed Spellbook", "Glacial Augment", "Stormraider's Surge"],
    )
    def test_the_three_zero_damage_keystones_declare_a_structural_zero(self, name):
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition is Disposition.STRUCTURAL_ZERO
        assert effect.receipts[0].startswith(f"{name} deals no damage in any fight:")

    @pytest.mark.parametrize(
        "name",
        [
            "Conqueror",
            "Fleet Footwork",
            "Aftershock",
            "Guardian",
            "Dark Harvest",
        ],
    )
    def test_the_five_channel_less_keystones_declare_a_withhold(self, name):
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition is Disposition.WITHHELD
        assert effect.receipts[0].startswith(f"{name} is not priced:")

    def test_stormraiders_zero_discloses_its_one_swiftmarch_caveat(self):
        effect = rune_effects.resolve_rune("Stormraider's Surge")
        assert any("Swiftmarch" in note for note in effect.receipts)

    def test_dark_harvests_missing_health_gate_is_the_stated_reason(self):
        # The cache carries every term of its damage and no threshold, so
        # the engine cannot say when the reap lands.
        assert "health_threshold" not in _cached("Dark Harvest")
        effect = rune_effects.resolve_rune("Dark Harvest")
        assert "maximum health" in effect.zero_policy.reason
        assert any("soul" in note for note in effect.receipts)

    def test_a_receipt_without_a_reason_is_rejected(self):
        with pytest.raises(ValueError, match="reason"):
            rune_effects.RuneNoDamageEffect(
                rune_name="Synthetic",
                zero_policy=rune_effects.ZeroPolicy(Disposition.WITHHELD, "  "),
            )


class TestRuneCatalog:
    def test_the_whole_roster_is_listed_with_its_slot(self):
        catalog = rune_effects.rune_catalog()
        assert len(catalog) == 62
        by_name = {entry["name"]: entry for entry in catalog}
        assert by_name["Electrocute"]["path"] == "Domination"
        assert by_name["Electrocute"]["row"] == 0
        assert by_name["Coup de Grace"]["row"] == 3
        assert all(entry["path"] for entry in catalog)
        assert all(entry["icon"] for entry in catalog)
        assert {entry["row"] for entry in catalog} == {0, 1, 2, 3}

    def test_every_keystone_and_the_four_exemplars_are_implemented(self):
        by_name = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        keystones = [entry for entry in by_name.values() if entry["row"] == 0]
        assert len(keystones) == 17
        assert all(entry["implemented"] is True for entry in keystones)
        for name in ("Absolute Focus", "Coup de Grace", "Scorch", "Cosmic Insight"):
            assert by_name[name]["implemented"] is True, name

    def test_an_uncompiled_rune_is_published_greyed_out(self, monkeypatch):
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS,
            "Synthetic Keystone",
            {"name": "Synthetic Keystone", "path": "Sorcery", "icon": "x"},
        )
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        assert catalog["Synthetic Keystone"]["implemented"] is False

    def test_the_declared_option_reaches_the_catalog(self):
        by_name = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        options = by_name["Absolute Focus"]["options"]
        assert [option["key"] for option in options] == ["above_health_threshold"]
        assert options[0]["default"] == 1.0
        assert options[0]["disclosure"]

    def test_the_shard_table_publishes_three_rows_of_three(self):
        catalog = rune_effects.shard_catalog()
        assert [row["row"] for row in catalog] == [1, 2, 3]
        assert [row["name"] for row in catalog] == ["Offense", "Flex", "Defense"]
        assert all(len(row["options"]) == 3 for row in catalog)
        assert catalog[0]["options"][0]["name"] == "Adaptive Force"
        # Every shard compiles; tests/test_rune_shards.py prices each one.
        assert all(
            option["implemented"] for row in catalog for option in row["options"]
        )


class TestValidateKeystoneRequest:
    def test_default_empty(self):
        assert rune_effects.validate_rune_page(None).keystone == ""
        assert rune_effects.validate_rune_page("").keystone == ""

    def test_valid_name_passes_through(self):
        page = rune_effects.validate_rune_page("Electrocute")
        assert page.keystone == "Electrocute"

    def test_non_string_rejected(self):
        with pytest.raises(ValueError, match="keystone"):
            rune_effects.validate_rune_page(42)

    def test_every_cached_keystone_is_selectable(self):
        for name, entry in rune_effects.RUNE_EFFECTS.items():
            if entry.get("row") != 0:
                continue
            assert rune_effects.validate_rune_page(name).keystone == name

    def test_a_minor_rune_is_not_a_keystone(self):
        with pytest.raises(ValueError, match="minor rune"):
            rune_effects.validate_rune_page("Scorch")

    def test_uncompiled_rejected(self, monkeypatch):
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS, "Synthetic Keystone", {"name": "Synthetic"}
        )
        with pytest.raises(ValueError, match="not modeled"):
            rune_effects.validate_rune_page("Synthetic Keystone")


class TestRefreshRuneEffects:
    def test_refresh_rereads_the_cache_in_place(self, monkeypatch):
        try:
            monkeypatch.setattr(
                rune_effects, "_load_rune_cache", lambda: {"Stub": {"name": "Stub"}}
            )
            rune_effects.refresh_rune_effects()
            assert set(rune_effects.RUNE_EFFECTS) == {"Stub"}
        finally:
            monkeypatch.undo()
            rune_effects.refresh_rune_effects()
        assert "Electrocute" in rune_effects.RUNE_EFFECTS
        assert rune_effects.RUNE_SHARDS["slots"]
        assert rune_effects.ADAPTIVE_FORCE["attack_damage_ratio"] == 0.6


class TestTheSharedTableAccessors:
    """The doors every compiler reads a table through, and what each refuses.

    Three of them, and the difference between them is what a table's columns
    *are*: ``required_leveling`` and ``required_level_table`` read champion
    levels, ``keyed_columns`` reads a table keyed by something else, and
    ``threshold_gates`` reads a list of (threshold, bonus) pairs. They live in
    ``rune_effects`` rather than in one path module because runes from three
    paths read them.
    """

    def test_a_level_table_may_be_either_width_the_wiki_renders(self):
        """Twenty columns from an explicit range, eighteen from a stepless one.

        Cheap Shot's table states ``1 to 20 by 1`` and renders twenty;
        Sudden Impact's states ``20 to 80`` and renders Module:Ability
        progression's default eighteen. Both are complete.
        """
        assert rune_effects.LEVEL_TABLE_SIZES == (18, 20)
        widths = {
            name: len(
                rune_effects.required_leveling(
                    name, rune_effects.RuneValues(name, _cached(name))
                )
            )
            for name in ("Cheap Shot", "Sudden Impact")
        }
        assert widths == {"Cheap Shot": 20, "Sudden Impact": 18}

    @pytest.mark.parametrize("width", [17, 19, 21])
    def test_any_other_width_is_still_a_degraded_parse(self, width):
        """The relaxation must not admit a twenty-level table missing columns."""
        values = rune_effects.RuneValues("Synthetic", {"leveling": [[1.0] * width]})
        with pytest.raises(KeyError, match="Synthetic.*18 or 20"):
            rune_effects.required_leveling("Synthetic", values)

    def test_a_keyed_table_is_read_by_its_own_rule_not_the_level_one(self):
        """Gathering Storm states eight minute columns, and eight is enough."""
        name = "Gathering Storm"
        values = rune_effects.RuneValues(name, _cached(name))
        assert len(rune_effects.keyed_columns(name, values, "leveling", 1)) == 8
        with pytest.raises(KeyError, match="18 or 20"):
            rune_effects.required_leveling(name, values, "leveling", 1)

    def test_a_keyed_table_of_one_column_states_no_step(self):
        values = rune_effects.RuneValues("Synthetic", {"leveling": [[3.0]]})
        with pytest.raises(KeyError, match="needs at least two"):
            rune_effects.keyed_columns("Synthetic", values, "leveling", 0)

    def test_threshold_gates_read_both_halves_of_each_pair(self):
        name = "Transcendence"
        values = rune_effects.RuneValues(name, _cached(name))
        gates = rune_effects.threshold_gates(name, values, "ability_haste_level_gates")
        assert gates == ((5, 5.0), (8, 5.0))

    def test_an_empty_gate_list_is_a_degraded_parse(self):
        values = rune_effects.RuneValues("Synthetic", {"gates": []})
        with pytest.raises(KeyError, match="states no gates"):
            rune_effects.threshold_gates("Synthetic", values, "gates")
