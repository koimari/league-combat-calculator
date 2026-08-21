"""Keystone/rune coverage audit (HANDOVER §8.3).

Locks the wave-2 decisions and invariants:

1. Unsealed Spellbook books no damage and says so with a receipt.  MERGE:
   it is no longer a raise — this branch compiles it to a
   ``RuneNoDamageEffect`` carrying a ``STRUCTURAL_ZERO`` disposition and
   the reason (RUNES-API), so the refusal is a value the page can carry
   rather than an exception a caller must catch.
2. The compiled roster exactly matches the cached keystone registry (all
   seventeen row-0 runes); the catalog flags coverage per keystone.
3. keystone_options is exposed ONLY for keystones the engine consumes
   (Fleet Footwork starting_charges, Conqueror starting_stacks); accepting
   an option the engine ignores would break score-vs-receipt parity.
4. Degraded parses fail closed naming the rune and key, never with a
   bare unpack/TypeError.
5. Every compiled keystone's sourced timing/ratio fields are sane, so a
   future wiki reparse that degrades a table fails here first.
6. The five utility keystones (Guardian, Aftershock, Glacial Augment,
   Stormraider's Surge, Grasp) fail the compiled score path by design and
   /api/optimize still returns ranked builds via the named-receipt
   fallback — score-vs-receipt parity preserved.
"""

import math

import pytest

from src.calculator import rune_effects

COMPILED_KEYSTONES = frozenset(rune_effects._KEYSTONE_COMPILERS)
# MERGE: nothing in the keystone row is refused outright any more; the
# damageless ones compile to a ``RuneNoDamageEffect`` instead.
NO_DAMAGE_KEYSTONES = frozenset(rune_effects._NO_DAMAGE_KEYSTONES)


def _registry_names():
    # MERGE: ``RUNE_EFFECTS`` is the WHOLE 62-rune roster now (ours' page
    # architecture), so the keystone question is asked of row 0.
    return frozenset(
        name
        for name, entry in rune_effects.RUNE_EFFECTS.items()
        if isinstance(entry, dict) and entry.get("row") == rune_effects.KEYSTONE_ROW
    )


# ---------------------------------------------------------------------------
# 1. Unsealed Spellbook decision
# ---------------------------------------------------------------------------


class TestUnsealedSpellbookDecision:
    def test_it_compiles_to_a_structural_zero_carrying_the_reason(self):
        # MERGE: the decision is unchanged (no summoner-spell model, no
        # sourced combat number), but it is now DECLARED rather than
        # raised: a damageless rune is a value with a disposition.
        effect = rune_effects.resolve_keystone("Unsealed Spellbook")
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.rune_name == "Unsealed Spellbook"
        assert (
            effect.zero_policy.disposition is rune_effects.Disposition.STRUCTURAL_ZERO
        )
        reason = effect.zero_policy.reason
        assert "summoner spells" in reason
        assert "no source states a combat number" in reason

    def test_request_validation_accepts_it_and_books_no_damage(self):
        assert (
            rune_effects.validate_rune_page("Unsealed Spellbook").keystone
            == "Unsealed Spellbook"
        )

    def test_catalog_serves_it_as_a_declared_zero(self):
        by_name = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        # It has a compiler now, so the catalog no longer greys it out;
        # the zero is the model, and the receipt says why.
        assert by_name["Unsealed Spellbook"]["implemented"] is True
        assert by_name["Unsealed Spellbook"]["path"] == "Inspiration"

    def test_assumptions_document_the_decision(self):
        joined = " ".join(rune_effects.ASSUMPTIONS)
        assert "Unsealed Spellbook" in joined
        assert "summoner-spell" in joined


# ---------------------------------------------------------------------------
# 2. Roster completeness
# ---------------------------------------------------------------------------


class TestRosterCoverage:
    def test_every_registry_keystone_is_accounted_for(self):
        assert _registry_names() == COMPILED_KEYSTONES
        assert len(_registry_names()) == 17
        assert len(COMPILED_KEYSTONES) == 17
        assert NO_DAMAGE_KEYSTONES == {"Unsealed Spellbook"}

    def test_catalog_implemented_flags_match_the_compilers(self):
        by_name = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        assert _registry_names() <= set(by_name)
        for name in COMPILED_KEYSTONES:
            assert by_name[name]["implemented"] is True

    def test_every_compiled_effect_keeps_its_registry_name(self):
        # MERGE: ``keystone_name`` -> ``rune_name`` (one vocabulary for
        # keystones, minors and shards alike).
        for name in COMPILED_KEYSTONES:
            effect = rune_effects.resolve_keystone(name)
            assert effect.rune_name == name


# ---------------------------------------------------------------------------
# 3. keystone_options parity
# ---------------------------------------------------------------------------


class TestKeystoneOptionsParity:
    def test_options_exist_only_for_engine_consumed_state(self):
        assert set(rune_effects.keystone_input_options_meta()) == {
            "Fleet Footwork",
            "Conqueror",
        }

    @pytest.mark.parametrize(
        "keystone",
        [
            "Electrocute",
            "First Strike",
            "Press the Attack",
            "Arcane Comet",
            "Summon Aery",
            "Guardian",
            "Aftershock",
            "Grasp of the Undying",
            "Hail of Blades",
            "Lethal Tempo",
            "Glacial Augment",
            "Stormraider's Surge",
            "Deathfire Touch",
            "Dark Harvest",
            "Unsealed Spellbook",
        ],
    )
    def test_unexposed_keystones_reject_any_option(self, keystone):
        with pytest.raises(ValueError, match="Unknown option"):
            rune_effects.validate_keystone_options({"starting_stacks": 0}, keystone)

    def test_no_keystone_selected_rejects_options(self):
        with pytest.raises(ValueError, match="Unknown option"):
            rune_effects.validate_keystone_options({"starting_charges": 0}, "")

    def test_defaults_round_trip(self):
        assert rune_effects.validate_keystone_options(None, "Fleet Footwork") == {
            "starting_charges": 0
        }
        assert rune_effects.validate_keystone_options(None, "Conqueror") == {
            "starting_stacks": 0
        }

    def test_option_bounds_match_the_compiled_effect(self):
        fleet = rune_effects.resolve_keystone("Fleet Footwork")
        assert (
            rune_effects.keystone_input_options_meta()["Fleet Footwork"]["options"][
                "starting_charges"
            ]["max"]
            == fleet.charge_cap
        )
        conqueror = rune_effects.resolve_keystone("Conqueror")
        assert (
            rune_effects.keystone_input_options_meta()["Conqueror"]["options"][
                "starting_stacks"
            ]["max"]
            == conqueror.max_stacks
        )


# ---------------------------------------------------------------------------
# 4. Fail-closed robustness on degraded parses
# ---------------------------------------------------------------------------


def _patch_registry(broken_effects_by_name):
    broken = {name: dict(entry) for name, entry in rune_effects.RUNE_EFFECTS.items()}
    for name, effects in broken_effects_by_name.items():
        broken[name] = dict(broken[name])
        broken[name]["effects"] = effects
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
    return monkeypatch


class TestFailClosedOnDegradedParses:
    def test_malformed_melee_ranged_pair_names_rune_and_key(self):
        # Every melee/ranged split is keyed by what it measures, so First
        # Strike's pair is its gold conversion rather than a bare pair.
        effects = dict(rune_effects.RUNE_EFFECTS["First Strike"]["effects"])
        effects["gold_conversion_ratios"] = [0.5, 0.35, 0.2]
        monkeypatch = _patch_registry({"First Strike": effects})
        try:
            with pytest.raises(KeyError, match=r"First Strike.*gold_conversion_ratios"):
                rune_effects.resolve_keystone("First Strike")
        finally:
            monkeypatch.undo()

    def test_non_list_leveling_names_rune_and_key(self):
        effects = dict(rune_effects.RUNE_EFFECTS["Electrocute"]["effects"])
        effects["leveling"] = {"leveling": "oops"}
        monkeypatch = _patch_registry({"Electrocute": effects})
        try:
            with pytest.raises(KeyError, match=r"Electrocute.*leveling"):
                rune_effects.resolve_keystone("Electrocute")
        finally:
            monkeypatch.undo()

    def test_non_numeric_leveling_table_names_rune_and_key(self):
        effects = dict(rune_effects.RUNE_EFFECTS["Electrocute"]["effects"])
        effects["leveling"] = [["not", "a", "number"]]
        monkeypatch = _patch_registry({"Electrocute": effects})
        try:
            with pytest.raises(KeyError, match=r"Electrocute.*leveling"):
                rune_effects.resolve_keystone("Electrocute")
        finally:
            monkeypatch.undo()


# ---------------------------------------------------------------------------
# 5. Sourced-value sanity across every compiled keystone
# ---------------------------------------------------------------------------


class TestSourcedValueSanity:
    def test_proc_class_fields_are_positive_and_finite(self):
        for name in COMPILED_KEYSTONES:
            effect = rune_effects.resolve_keystone(name)
            if isinstance(effect, rune_effects.RuneProcEffect):
                assert effect.stacks_required >= 1
                assert effect.stack_window_seconds > 0
                assert effect.cooldown_seconds > 0
                assert effect.proc_delay_seconds >= 0
            elif isinstance(effect, rune_effects.RuneProcAmpEffect):
                assert effect.stacks_required >= 1
                assert effect.stack_duration_seconds > 0
                # Press the Attack's lasting amp is declared in the amp
                # chain too, for the same one-number-one-home reason.
                assert effect.cooldown_seconds > 0
            elif isinstance(effect, rune_effects.RuneAbilityProcEffect):
                assert len(effect.cooldown_by_level) >= 20
                assert all(cd > 0 for cd in effect.cooldown_by_level)
                assert effect.proc_delay_seconds > 0
                assert effect.assumed_travel_distance > 0
                assert effect.distance_amp_ratio >= 0
            elif isinstance(effect, rune_effects.RuneWindowAmpEffect):
                # The window and its bonus-damage ratio are the amp chain's
                # OPENING_WINDOW declaration, not fields here; what is left
                # on the effect is the gold accounting.
                assert effect.activation_gold >= 0
                assert 0 < effect.gold_conversion_melee < 1
                assert 0 < effect.gold_conversion_ranged < 1

    def test_aery_guardian_aftershock_fields_are_sane(self):
        for name in COMPILED_KEYSTONES:
            effect = rune_effects.resolve_keystone(name)
            if isinstance(effect, rune_effects.KeystoneAeryEffect):
                assert len(effect.damage_by_level) >= 20
                assert len(effect.shield_by_level) >= 20
                assert effect.damage_flight_seconds > 0
                assert effect.shield_flight_seconds > 0
                assert effect.shield_duration_seconds > 0
                assert effect.linger_seconds > 0
            elif isinstance(effect, rune_effects.KeystoneGuardianEffect):
                assert len(effect.threshold_by_level) >= 20
                assert len(effect.shield_by_level) >= 20
                assert len(effect.cooldown_by_level) >= 20
                assert effect.trigger_window_seconds > 0
                assert effect.shield_duration_seconds > 0
                assert effect.bonus_health_ratio >= 0
            elif isinstance(effect, rune_effects.KeystoneAftershockEffect):
                assert len(effect.resistance_cap_by_level) >= 20
                assert len(effect.shockwave_damage_by_level) >= 20
                assert effect.cooldown_seconds > 0
                assert effect.duration_seconds > 0
                assert effect.shockwave_radius > 0
                assert effect.flat_armor > 0
                assert effect.flat_magic_resistance > 0

    def test_stack_keystone_fields_are_sane(self):
        for name in COMPILED_KEYSTONES:
            effect = rune_effects.resolve_keystone(name)
            if isinstance(effect, rune_effects.KeystoneGraspEffect):
                assert effect.max_stacks >= 1
                assert effect.stack_cadence_seconds > 0
                assert effect.stack_generation_seconds > 0
                assert effect.ready_window_seconds > 0
                assert all(
                    0 < ratio < 0.1 for ratio in effect.damage_melee_ranged_ratios
                )
            elif isinstance(effect, rune_effects.KeystoneHailOfBladesEffect):
                assert len(effect.damage_by_level) >= 20
                assert effect.initial_stacks >= 1
                assert effect.stack_duration_seconds > 0
                assert effect.cooldown_seconds > 0
                assert effect.reset_stack_limit >= 0
            elif isinstance(effect, rune_effects.KeystoneLethalTempoEffect):
                assert len(effect.bolt_damage_melee_by_level) >= 20
                assert len(effect.bolt_damage_ranged_by_level) >= 20
                assert effect.max_stacks >= 1
                assert effect.stack_duration_seconds > 0
                assert effect.expiry_step_seconds > 0
            elif isinstance(effect, rune_effects.KeystoneConquerorEffect):
                assert len(effect.adaptive_force_by_level) >= 20
                assert len(effect.adaptive_force_max_by_level) >= 20
                assert effect.max_stacks >= 1
                assert effect.stacks_per_application >= 1
                assert effect.stack_duration_seconds > 0
                assert effect.cast_instance_interval_seconds > 0
                assert all(0 < ratio < 1 for ratio in effect.heal_melee_ranged_ratios)

    def test_glacial_stormraider_fleet_deathfire_dark_harvest_are_sane(self):
        for name in COMPILED_KEYSTONES:
            effect = rune_effects.resolve_keystone(name)
            if isinstance(effect, rune_effects.KeystoneGlacialEffect):
                assert effect.cooldown_seconds > 0
                assert effect.ray_count >= 1
                assert effect.zone_radius_units > 0
                assert effect.zone_width_units > 0
                assert effect.zone_base_duration_seconds > 0
                assert effect.slow_base_ratio >= 0
                assert 0 < effect.damage_reduction_ratio < 1
            elif isinstance(effect, rune_effects.KeystoneStormraiderEffect):
                assert len(effect.cooldown_by_level) >= 20
                assert 0 < effect.damage_threshold_ratio < 1
                assert effect.damage_window_seconds > 0
                assert effect.duration_seconds > 0
                assert 0 <= effect.slow_resist_ratio <= 1
            elif isinstance(effect, rune_effects.KeystoneFleetEffect):
                assert len(effect.heal_melee_by_level) >= 20
                assert len(effect.heal_ranged_by_level) >= 20
                assert effect.charge_cap > 0
                assert effect.move_speed_duration_seconds > 0
                assert 0 < effect.minion_heal_effectiveness < 1
            elif isinstance(effect, rune_effects.KeystoneDeathfireEffect):
                assert len(effect.damage_by_level) >= 20
                assert len(effect.amplified_damage_by_level) >= 20
                assert effect.tick_interval_seconds > 0
                assert effect.amp_delay_seconds > 0
                assert 0 < effect.amp_ratio < 1
                assert set(effect.duration_by_category) >= {
                    "spell_damage",
                    "area_damage",
                    "persistent_damage",
                    "persistent_area_damage",
                    "pet_damage",
                }
                assert all(
                    duration > 0 for duration in effect.duration_by_category.values()
                )
            elif isinstance(effect, rune_effects.KeystoneDarkHarvestEffect):
                assert effect.cooldown_seconds > 0
                assert 0 < effect.health_threshold_ratio < 1
                assert effect.base_damage > 0
                assert effect.soul_damage > 0
                assert effect.proc_delay_seconds > 0
                assert effect.takedown_reset_seconds > 0

    def test_all_timing_fields_are_finite(self):
        for name in COMPILED_KEYSTONES:
            effect = rune_effects.resolve_keystone(name)
            for field_name in ("cooldown_seconds", "proc_delay_seconds"):
                value = getattr(effect, field_name, None)
                if value is not None:
                    assert math.isfinite(value)
            for table_name in (
                "cooldown_by_level",
                "damage_by_level",
                "shield_by_level",
                "threshold_by_level",
            ):
                table = getattr(effect, table_name, None)
                if table:
                    assert all(math.isfinite(value) for value in table)


# ---------------------------------------------------------------------------
# 6. Score-vs-receipt parity for utility keystones (optimize fallback)
# ---------------------------------------------------------------------------


class TestOptimizeFallbackParity:
    """The compiled score path rejects the five utility keystones with named
    receipts; /api/optimize must still return ranked builds through the
    receipt-walk fallback rather than erroring or silently dropping them."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limits(self):
        import src.app as app_module

        previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
        app_module.app.config["RATE_LIMIT_ENABLED"] = False
        yield
        app_module.app.config["RATE_LIMIT_ENABLED"] = previous

    @pytest.mark.parametrize(
        "keystone",
        [
            "Guardian",
            "Aftershock",
            "Glacial Augment",
            "Stormraider's Surge",
            "Grasp of the Undying",
        ],
    )
    def test_optimize_returns_ranked_builds_via_receipt_fallback(self, keystone):
        import src.app as app_module

        payload = {
            "champion": "Ahri",
            "level": 9,
            "items": [],
            "fight_mode": "one_rotation",
            "keystone": keystone,
            "enemies": [{"champion": "Aatrox", "level": 9, "items": []}],
            "locked_items": [],
            "max_legendary_slots": 2,
        }
        response = app_module.app.test_client().post("/api/optimize", json=payload)
        assert response.status_code == 200, response.get_json()
        data = response.get_json()
        assert data.get("ranked_builds")
        for ranked in data["ranked_builds"][:1]:
            assert ranked["items"] is not None
            assert ranked["total_damage"] > 0

    def test_optimize_damage_class_keystones_stay_compiled(self):
        import src.app as app_module

        payload = {
            "champion": "Ahri",
            "level": 9,
            "items": [],
            "fight_mode": "one_rotation",
            "keystone": "Electrocute",
            "enemies": [{"champion": "Aatrox", "level": 9, "items": []}],
            "locked_items": [],
            "max_legendary_slots": 2,
        }
        response = app_module.app.test_client().post("/api/optimize", json=payload)
        assert response.status_code == 200, response.get_json()
