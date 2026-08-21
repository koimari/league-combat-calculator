"""The flat rune amplifier: one ratio over the instances a rune filters to.

Three roster runes amplify damage on a condition the ledger's health walk
cannot answer, and this file is their contract.

* **Last Stand** gates on the *holder's* health, which the pair engine does
  not track — so the health is a declared option and the default is the
  un-triggered state.
* **Axiom Arcanist** gates on which slot dealt the damage: the ultimate's
  rows and nothing else.
* **Cut Down** is here for the negative result. Its cached description gates
  on the *target's* current health like Coup de Grace, so it needs no kind of
  its own and compiles to the conditional amp that already existed.

Every number is quoted against the cached description it came out of, and
each rune is priced through the real engine — with its condition met and
with it absent.
"""

import pytest

import src.app as app_module
from src.calculator import rune_effects
from src.calculator.ability_spec import DamagePart
from src.calculator.calculate import calculate_payload
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.rune_paths import precision, sorcery

# ---------------------------------------------------------------------------
# What the cache states
# ---------------------------------------------------------------------------


class TestCutDownNeedsNoNewKind:
    """The cache: deal 8% increased damage to champions above 60% health."""

    def test_it_compiles_to_the_target_health_gate_the_cache_states(self):
        effect = rune_effects.resolve_rune("Cut Down")
        assert isinstance(effect, rune_effects.RuneConditionalAmpEffect)
        assert effect.condition is rune_effects.AmpCondition.TARGET_ABOVE
        assert effect.health_ratio == pytest.approx(0.60)
        assert effect.amp_ratio == pytest.approx(0.08)
        assert effect.breakdown_key == "rune_Cut Down"
        assert "above 60% of its maximum health" in effect.disclosures[0]

    def test_the_row_it_shares_with_coup_de_grace_reads_the_other_side(self):
        """One helper, two runes: the side each prices is the declaration."""
        coup = rune_effects.resolve_rune("Coup de Grace")
        assert coup.condition is rune_effects.AmpCondition.TARGET_BELOW
        assert "below 40% of its maximum health" in coup.disclosures[0]

    def test_a_description_stating_the_other_side_is_refused(self):
        with pytest.raises(KeyError, match="prices the 'target_above' one"):
            precision._compile_cut_down(
                {
                    "effects": {
                        "damage_amp_health_gate": "target_below",
                        "damage_amp_health_ratio": 0.4,
                        "damage_amp_ratio": 0.08,
                    }
                }
            )


class TestLastStandsRamp:
    """The cache: 5% below 60% maximum health, up to 11% below 30%."""

    def test_the_cache_carries_both_ends_of_the_ramp(self):
        effects = rune_effects.RUNE_EFFECTS["Last Stand"]["effects"]
        assert effects["damage_amp_ratio"] == pytest.approx(0.05)
        assert effects["damage_amp_health_ratio"] == pytest.approx(0.60)
        assert effects["escalated_damage_amp_ratio"] == pytest.approx(0.11)
        assert effects["escalated_damage_amp_health_ratio"] == pytest.approx(0.30)
        assert effects["escalated_damage_amp_health_gate"] == "self_below"

    @pytest.mark.parametrize(
        "health_percent,ratio",
        [
            (100, 0.0),  # full health: the rune has not armed
            (60, 0.0),  # exactly at the gate: "below" excludes it
            (45, 0.08),  # halfway down the 60→30 span, halfway up 5%→11%
            (30, 0.11),  # the escalated end
            (5, 0.11),  # and it does not grow past it
        ],
    )
    def test_it_ramps_linearly_between_the_two_ends(self, health_percent, ratio):
        effect = rune_effects.resolve_rune("Last Stand")
        assert isinstance(effect, rune_effects.RuneFlatAmpEffect)
        assert effect.amp_ratio(_amp_context(health_percent)) == pytest.approx(ratio)

    def test_it_amplifies_every_slot_because_its_gate_names_none(self):
        effect = rune_effects.resolve_rune("Last Stand")
        for slot in ("", "Q", "R"):
            assert effect.amp_ratio(_amp_context(30, slot=slot)) == pytest.approx(0.11)

    def test_the_default_is_the_un_triggered_state_and_it_says_so(self):
        effect = rune_effects.resolve_rune("Last Stand")
        assert effect.amp_ratio(_amp_context(None)) == 0.0
        assert "'self_health_percent'" in effect.disclosures[0]
        assert "default of 100 is the un-triggered state" in effect.disclosures[0]
        assert "rise is read as linear" in effect.disclosures[1]

    def test_the_declared_option_is_a_bounded_count(self):
        (option,) = precision.OPTIONS["Last Stand"]
        assert option.key == "self_health_percent"
        assert option.kind is rune_effects.RuneOptionKind.COUNT
        assert (option.default, option.bounds) == (100.0, (0.0, 100.0))
        with pytest.raises(ValueError, match="between 0 and 100"):
            option.validated(101)
        with pytest.raises(ValueError, match="whole number"):
            option.validated(42.5)

    def test_a_ramp_that_does_not_rise_toward_lower_health_is_refused(self):
        with pytest.raises(KeyError, match="not a rise toward lower health"):
            precision._compile_last_stand(
                {
                    "effects": {
                        "damage_amp_health_gate": "self_below",
                        "damage_amp_health_ratio": 0.6,
                        "damage_amp_ratio": 0.11,
                        "escalated_damage_amp_health_gate": "self_below",
                        "escalated_damage_amp_health_ratio": 0.3,
                        "escalated_damage_amp_ratio": 0.05,
                    }
                }
            )

    def test_a_gate_on_the_target_is_refused(self):
        with pytest.raises(KeyError, match="states a 'target_below' gate"):
            precision._compile_last_stand(
                {"effects": {"damage_amp_health_gate": "target_below"}}
            )

    def test_a_missing_escalated_end_is_refused_rather_than_flattened(self):
        with pytest.raises(KeyError, match="escalated_damage_amp_health_gate"):
            precision._compile_last_stand(
                {
                    "effects": {
                        "damage_amp_health_gate": "self_below",
                        "damage_amp_health_ratio": 0.6,
                        "damage_amp_ratio": 0.05,
                    }
                }
            )


class TestAxiomArcanistsSlotFilter:
    """The cache: the ultimate has 12% increased damage, 8% if area of effect."""

    def test_the_cache_carries_both_rates(self):
        effects = rune_effects.RUNE_EFFECTS["Axiom Arcanist"]["effects"]
        assert effects["ultimate_damage_amp_ratio"] == pytest.approx(0.12)
        assert effects["ultimate_aoe_damage_amp_ratio"] == pytest.approx(0.08)

    def test_it_pays_the_ultimate_slot_alone(self):
        effect = rune_effects.resolve_rune("Axiom Arcanist")
        assert isinstance(effect, rune_effects.RuneFlatAmpEffect)
        assert effect.amp_ratio(_amp_context(None, slot="R")) == pytest.approx(0.08)
        for slot in ("", "Q", "W", "E"):
            assert effect.amp_ratio(_amp_context(None, slot=slot)) == 0.0

    def test_the_single_target_rate_is_the_option_turned_off(self):
        effect = rune_effects.resolve_rune("Axiom Arcanist")
        single = _amp_context(
            None,
            slot="R",
            options={"Axiom Arcanist": {"area_of_effect_ultimate": 0}},
        )
        assert effect.amp_ratio(single) == pytest.approx(0.12)
        assert "priced at 8%, its area-of-effect rate" in effect.disclosures[1]
        assert "12% for a single-target ultimate" in effect.disclosures[1]

    def test_its_takedown_refund_and_healing_are_withheld_out_loud(self):
        effect = rune_effects.resolve_rune("Axiom Arcanist")
        assert "cooldown refund on takedown" in effect.disclosures[2]

    def test_the_declared_option_is_a_switch_defaulting_to_the_lower_rate(self):
        (option,) = sorcery.OPTIONS["Axiom Arcanist"]
        assert option.key == "area_of_effect_ultimate"
        assert option.kind is rune_effects.RuneOptionKind.SWITCH
        assert (option.default, option.bounds) == (1.0, (0.0, 1.0))

    def test_a_reduction_that_does_not_reduce_is_refused(self):
        with pytest.raises(KeyError, match="which is no reduction"):
            sorcery._compile_axiom_arcanist(
                {
                    "effects": {
                        "ultimate_damage_amp_ratio": 0.08,
                        "ultimate_aoe_damage_amp_ratio": 0.12,
                    }
                }
            )


# ---------------------------------------------------------------------------
# What the fight does with them
# ---------------------------------------------------------------------------
#
# 300 raw magic into 100 magic resistance is 150; Q's 6s cooldown casts it at
# 0, 6, 12 and 18 seconds of a 20s fight. R casts once for 400 raw = 200.
# The fight's ledger is therefore 4 x 150 + 200 = 800, and the target's
# 10 000 health keeps every target-health gate on the same side all fight.

_STATS = {
    "armor_penetration_bonus_percent": 0.0,
    "armor_penetration_percent": 0.0,
    "basic_ability_haste": 0.0,
    "bonus_health": 0.0,
    "bonus_mana": 0.0,
    "flat_armor_penetration": 0.0,
    "is_melee": True,
    "lethality": 0.0,
    "magic_penetration_flat": 0.0,
    "magic_penetration_percent": 0.0,
    "max_mana": 0.0,
    "move_speed": 0.0,
    "omnivamp_percent": 0.0,
    "resource_regen_per_second": 0.0,
    "ultimate_haste": 0.0,
    "attack_damage": 100.0,
    "base_attack_damage": 60.0,
    "bonus_attack_damage": 40.0,
    "ability_power": 0.0,
    "attack_speed": 0.7,
    "attack_speed_ratio": 0.7,
    "critical_strike_chance": 0.0,
    "health": 2000.0,
    "armor": 50.0,
    "magic_resistance": 50.0,
    "level": 18,
    "ability_haste": 0.0,
}
_ABILITIES = {
    "Q": {
        "name": "Test Q",
        "rank": 1,
        "cooldown": 6.0,
        "damage_type": "magic",
        "total_raw": 300.0,
        "parts": (DamagePart("magic", 300.0),),
    },
    "R": {
        "name": "Test R",
        "rank": 1,
        "cooldown": 100.0,
        "damage_type": "magic",
        "total_raw": 400.0,
        "parts": (DamagePart("magic", 400.0),),
    },
}
_Q_TOTAL = 600.0
_R_TOTAL = 200.0
_LEDGER = _Q_TOTAL + _R_TOTAL


def _fight(**overrides):
    config = {
        "target_health": 10_000.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": 20.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(dict(_STATS), _ABILITIES, [], FightConfig(**config))


class TestTheWalkerPricesTheFilteredSet:
    def test_the_bare_fight_is_the_ledger_the_amps_are_measured_against(self):
        bare = _fight()
        assert bare["total_damage"] == pytest.approx(_LEDGER)
        assert bare["breakdown"]["R"]["total_damage"] == pytest.approx(_R_TOTAL)

    def test_axiom_arcanist_amplifies_the_ultimate_row_and_nothing_else(self):
        result = _fight(minor_runes=("Axiom Arcanist",))
        row = result["breakdown"]["rune_Axiom Arcanist"]
        assert row["name"] == "Damage Amplification (Axiom Arcanist)"
        assert row["multiplier"] == pytest.approx(1.08)
        assert row["total_damage"] == pytest.approx(_R_TOTAL * 0.08)
        assert result["total_damage"] == pytest.approx(_LEDGER + 16.0)
        # One delta event, on the ultimate's own instance.
        assert [event["damage"] for event in row["damage_events"]] == [
            pytest.approx(16.0)
        ]

    def test_turning_its_area_of_effect_option_off_pays_the_higher_rate(self):
        result = _fight(
            minor_runes=("Axiom Arcanist",),
            rune_options={"Axiom Arcanist": {"area_of_effect_ultimate": 0}},
        )
        row = result["breakdown"]["rune_Axiom Arcanist"]
        assert row["multiplier"] == pytest.approx(1.12)
        assert row["total_damage"] == pytest.approx(_R_TOTAL * 0.12)
        assert result["total_damage"] == pytest.approx(_LEDGER + 24.0)

    def test_a_fight_with_no_ultimate_cast_says_it_amplified_nothing(self):
        result = _fight(
            minor_runes=("Axiom Arcanist",), cast_order=["Q"], auto_attacks_only=False
        )
        assert "rune_Axiom Arcanist" not in result["breakdown"]
        assert result["total_damage"] == pytest.approx(_Q_TOTAL)
        assert any(
            note.startswith("Axiom Arcanist amplified nothing")
            for note in result["notes"]
        )

    def test_last_stand_at_its_default_leaves_the_fight_untouched(self):
        result = _fight(minor_runes=("Last Stand",))
        assert result["total_damage"] == pytest.approx(_LEDGER)
        assert "rune_Last Stand" not in result["breakdown"]
        assert any(
            note.startswith("Last Stand amplified nothing") for note in result["notes"]
        )

    @pytest.mark.parametrize(
        "health_percent,ratio", [(45, 0.08), (30, 0.11), (10, 0.11)]
    )
    def test_last_stand_amplifies_the_whole_ledger_at_its_stated_health(
        self, health_percent, ratio
    ):
        result = _fight(
            minor_runes=("Last Stand",),
            rune_options={"Last Stand": {"self_health_percent": health_percent}},
        )
        row = result["breakdown"]["rune_Last Stand"]
        assert row["multiplier"] == pytest.approx(1.0 + ratio)
        assert row["total_damage"] == pytest.approx(_LEDGER * ratio)
        assert result["total_damage"] == pytest.approx(_LEDGER * (1.0 + ratio))

    def test_cut_down_amplifies_the_fight_against_a_target_that_stays_high(self):
        result = _fight(minor_runes=("Cut Down",))
        row = result["breakdown"]["rune_Cut Down"]
        assert row["multiplier"] == pytest.approx(1.08)
        assert row["total_damage"] == pytest.approx(_LEDGER * 0.08)

    def test_cut_down_against_a_target_it_drives_below_the_gate(self):
        """A 500-health target crosses 60% (300) during the opening exchange.

        The ledger opens with Q's 150 (500 left, above the gate) and R's 200
        (350 left, still above); the second Q meets 150 and is not amplified.
        The row is 8% of those two instances, not of the fight.
        """
        result = _fight(minor_runes=("Cut Down",), target_health=500.0)
        row = result["breakdown"]["rune_Cut Down"]
        assert row["total_damage"] == pytest.approx((150.0 + _R_TOTAL) * 0.08)

    def test_two_flat_amps_on_one_page_each_price_the_ledger_they_share(self):
        """Precision row 3 and Sorcery row 1 are legal together.

        Both occupy one position of the amplifier chain, so they read the one
        ledger the fight left them and are additive among themselves — the
        reading the chain's other shared position (``WHOLE_TOTAL``) already
        has. Neither amplifies the other's bonus.
        """
        result = _fight(
            minor_runes=("Last Stand", "Axiom Arcanist"),
            rune_options={"Last Stand": {"self_health_percent": 30}},
        )
        assert result["breakdown"]["rune_Last Stand"]["total_damage"] == pytest.approx(
            _LEDGER * 0.11
        )
        assert result["breakdown"]["rune_Axiom Arcanist"][
            "total_damage"
        ] == pytest.approx(_R_TOTAL * 0.08)
        assert result["total_damage"] == pytest.approx(_LEDGER + 88.0 + 16.0)


def _fight_with(monkeypatch, effect, **overrides):
    """One fight whose whole rune page is ``effect``.

    A synthetic effect has no roster entry to select it by, so the page is
    substituted where the fight compiles it. Everything downstream — the
    walk, the row, the notes — is the real engine's.
    """
    monkeypatch.setattr(rune_effects, "resolve_rune_page", lambda page: (effect,))
    return _fight(**overrides)


class TestTheKindsOwnContract:
    def test_a_rune_paying_two_ratios_at_once_is_refused(self, monkeypatch):
        """One breakdown row publishes one multiplier; two would be a fiction."""
        effect = rune_effects.RuneFlatAmpEffect(
            rune_name="Synthetic Two-Rate",
            breakdown_key="rune_Synthetic Two-Rate",
            display_name="Synthetic Two-Rate (rune)",
            amp_ratio=lambda context: 0.5 if context.slot == "R" else 0.25,
        )
        with pytest.raises(ValueError, match=r"pays \[0.25, 0.5\]"):
            _fight_with(monkeypatch, effect)

    def test_the_context_carries_the_facts_the_three_runes_decide_from(
        self, monkeypatch
    ):
        seen = []

        def probe(context):
            seen.append(context)
            return 0.0

        effect = rune_effects.RuneFlatAmpEffect(
            rune_name="Synthetic Probe",
            breakdown_key="rune_Synthetic Probe",
            display_name="Synthetic Probe (rune)",
            amp_ratio=probe,
        )
        _fight_with(monkeypatch, effect)
        assert {context.slot for context in seen} == {"Q", "R"}
        first = seen[0]
        assert (first.level, first.is_melee) == (18, True)
        assert first.target_max_health == pytest.approx(10_000.0)
        assert first.champion_stats["bonus_attack_damage"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# The public boundary
# ---------------------------------------------------------------------------
#
# Ahri at 18 with no items deals 693: Q 202.5, W 108, E 120, R 262.5.

_AHRI = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "fight_mode": "one_rotation",
    "target_health": 3000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}
_AHRI_TOTAL = 693.0
_AHRI_R = 262.5


class TestThroughTheRealPipeline:
    def test_the_bare_request_is_the_baseline_the_rest_are_read_against(self):
        bare = calculate_payload(dict(_AHRI))
        assert bare["total_damage"] == pytest.approx(_AHRI_TOTAL, abs=0.05)
        assert bare["breakdown"]["R"]["total_damage"] == pytest.approx(
            _AHRI_R, abs=0.05
        )

    def test_axiom_arcanist_prices_ahris_ultimate_row(self):
        result = calculate_payload({**_AHRI, "minor_runes": ["Axiom Arcanist"]})
        assert result["breakdown"]["rune_Axiom Arcanist"][
            "total_damage"
        ] == pytest.approx(_AHRI_R * 0.08, abs=0.05)
        assert result["total_damage"] == pytest.approx(_AHRI_TOTAL + 21.0, abs=0.05)

    def test_last_stand_prices_ahris_whole_fight_at_the_health_it_is_given(self):
        result = calculate_payload(
            {
                **_AHRI,
                "minor_runes": ["Last Stand"],
                "rune_options": {"Last Stand": {"self_health_percent": 45}},
            }
        )
        assert result["total_damage"] == pytest.approx(_AHRI_TOTAL * 1.08, abs=0.05)
        assert any("un-triggered state" in note for note in result["notes"])

    def test_cut_down_prices_a_target_that_never_leaves_the_gate(self):
        result = calculate_payload({**_AHRI, "minor_runes": ["Cut Down"]})
        assert result["total_damage"] == pytest.approx(_AHRI_TOTAL * 1.08, abs=0.05)

    def test_the_three_are_published_as_implemented_with_their_options(self):
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        for name in ("Cut Down", "Last Stand", "Axiom Arcanist"):
            assert catalog[name]["implemented"] is True, name
        assert [option["key"] for option in catalog["Last Stand"]["options"]] == [
            "self_health_percent"
        ]
        assert catalog["Axiom Arcanist"]["options"][0]["default"] == 1.0

    def test_an_option_the_rune_does_not_declare_is_refused(self):
        with pytest.raises(ValueError, match="declares no option 'health'"):
            rune_effects.validate_rune_page(
                "", ["Last Stand"], None, {"Last Stand": {"health": 30}}
            )


class TestOverHttp:
    """The same three runes, through the app the browser talks to."""

    def test_last_stand_and_axiom_arcanist_ride_one_legal_page(self):
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json={
                **_AHRI,
                "minor_runes": ["Last Stand", "Axiom Arcanist"],
                "rune_options": {"Last Stand": {"self_health_percent": 30}},
            },
        )
        assert response.status_code == 200
        breakdown = response.get_json()["breakdown"]
        assert breakdown["rune_Last Stand"]["total_damage"] == pytest.approx(
            _AHRI_TOTAL * 0.11, abs=0.05
        )
        assert breakdown["rune_Axiom Arcanist"]["total_damage"] == pytest.approx(
            _AHRI_R * 0.08, abs=0.05
        )

    def test_cut_down_answers_over_the_wire_too(self):
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate", json={**_AHRI, "minor_runes": ["Cut Down"]}
        )
        assert response.status_code == 200
        assert response.get_json()["breakdown"]["rune_Cut Down"][
            "total_damage"
        ] == pytest.approx(_AHRI_TOTAL * 0.08, abs=0.05)

    def test_last_stand_and_cut_down_share_a_row_and_the_page_says_so(self):
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json={**_AHRI, "minor_runes": ["Cut Down", "Last Stand"]},
        )
        assert response.status_code == 400
        assert "one rune per row" in response.get_json()["error"]

    def test_an_out_of_range_health_option_is_refused_by_name(self):
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json={
                **_AHRI,
                "minor_runes": ["Last Stand"],
                "rune_options": {"Last Stand": {"self_health_percent": 140}},
            },
        )
        assert response.status_code == 400
        assert "self_health_percent" in response.get_json()["error"]


def _amp_context(health_percent, *, slot="", options=None):
    """One amp context, with Last Stand's option set unless it is ``None``."""
    if options is None:
        options = (
            {}
            if health_percent is None
            else {"Last Stand": {"self_health_percent": health_percent}}
        )
    return rune_effects.RuneAmpContext(
        level=18,
        is_melee=False,
        champion_stats={"bonus_attack_damage": 0.0, "ability_power": 0.0},
        target_max_health=1000.0,
        options=options,
        slot=slot,
    )
