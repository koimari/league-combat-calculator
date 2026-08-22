"""Sorcery's minor runes: what each one compiles to, and what it moves.

Six runes land here beside A1's two exemplars — three adaptive-force grants
behind an explicit option, ability haste gated on champion level, a flat
share of movement speed, and the two whose halves this engine holds no
channel for. Every number is quoted against the cached description, and
every grant that reaches a stat is probed through the real pipeline.
"""

import pytest

from src.calculator import rune_effects, rune_parser
from src.calculator.calculate import calculate_payload
from src.calculator.rune_paths import sorcery


def _context(*, level=11, ability_power=0.0, bonus_attack_damage=0.0, options=None):
    return rune_effects.RuneStatContext(
        level=level,
        is_melee=False,
        bonus_attack_damage=bonus_attack_damage,
        ability_power=ability_power,
        options=options or {},
    )


def _request(**overrides):
    payload = {
        "champion": "Ahri",
        "level": 11,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 20.0,
    }
    payload.update(overrides)
    return payload


class TestTranscendence:
    """Sorcery row 2: ability haste at the levels the rune's own gates name."""

    def test_it_grants_the_gates_the_cache_states_and_nothing_below_them(self):
        """The cache states Level 5: +5 ability haste, Level 8: +5 more."""
        effect = rune_effects.resolve_rune("Transcendence")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.ABILITY_HASTE
        assert effect.amount(_context(level=4)) == 0.0
        assert effect.amount(_context(level=5)) == pytest.approx(5.0)
        assert effect.amount(_context(level=8)) == pytest.approx(10.0)
        assert effect.amount(_context(level=18)) == pytest.approx(10.0)

    def test_its_takedown_gate_is_disclosed_as_withheld(self):
        effect = rune_effects.resolve_rune("Transcendence")
        assert "5 at level 5, 5 at level 8" in effect.disclosures[0]
        assert "no takedowns to spend" in effect.disclosures[1]

    def test_a_record_stating_no_gates_fails_closed(self):
        with pytest.raises(KeyError, match="ability_haste_level_gates"):
            sorcery.COMPILERS["Transcendence"]({"effects": {}})
        with pytest.raises(KeyError, match="states no gates"):
            sorcery.COMPILERS["Transcendence"](
                {"effects": {"ability_haste_level_gates": []}}
            )

    def test_the_haste_reaches_the_fight_and_buys_casts(self):
        """Blackfire Torch's 20 haste plus the rune's 10 crosses a cadence."""
        request = _request(items=["Blackfire Torch"], fight_duration=30.0)
        bare = calculate_payload(dict(request))
        hasted = calculate_payload({**request, "minor_runes": ["Transcendence"]})
        assert bare["champion_stats"]["ability_haste"] == pytest.approx(20.0)
        assert hasted["champion_stats"]["ability_haste"] == pytest.approx(30.0)
        assert bare["breakdown"]["Q"]["casts"] == 5
        assert hasted["breakdown"]["Q"]["casts"] == 6
        assert bare["total_damage"] == pytest.approx(2591.5, abs=0.1)
        assert hasted["total_damage"] == pytest.approx(3077.7, abs=0.1)


class TestCelerity:
    """Sorcery row 2: a flat share of bonus movement speed, and its limits."""

    def test_it_grants_the_percent_the_cache_states(self):
        effect = rune_effects.resolve_rune("Celerity")
        assert effect.stat is rune_effects.RuneStat.MOVE_SPEED_PERCENT
        assert effect.amount(_context(level=1)) == pytest.approx(1.0)
        assert effect.amount(_context(level=18)) == pytest.approx(1.0)

    def test_the_effectiveness_half_is_withheld_without_inventing_its_share(self):
        """The cache carries no number for it, so neither does the receipt."""
        effect = rune_effects.resolve_rune("Celerity")
        assert "cache carries no share for it" in effect.disclosures[1]
        assert "7" not in effect.disclosures[1]

    def test_it_moves_the_stat_card_and_no_damage(self):
        bare = calculate_payload(_request())
        quick = calculate_payload(_request(minor_runes=["Celerity"]))
        assert bare["champion_stats"]["move_speed"] == pytest.approx(330.0)
        assert quick["champion_stats"]["move_speed"] == pytest.approx(333.3)
        assert quick["total_damage"] == pytest.approx(bare["total_damage"])

    def test_swiftmarch_converts_the_movement_speed_the_build_publishes(self):
        """The receipt's own claim, probed: one item, one movement speed."""
        request = _request(boots="Swiftmarch", role="mid", role_quest_complete=True)
        bare = calculate_payload(dict(request))
        quick = calculate_payload({**request, "minor_runes": ["Celerity"]})
        assert bare["champion_stats"]["move_speed"] == pytest.approx(395.0)
        assert quick["champion_stats"]["move_speed"] == pytest.approx(398.95)
        assert bare["champion_stats"]["ability_power"] == 21
        assert quick["champion_stats"]["ability_power"] == 22
        assert quick["total_damage"] > bare["total_damage"]


class TestWaterwalking:
    """Sorcery row 3: leveled adaptive force, live only in the river."""

    def test_it_grants_its_level_table_only_with_the_option_set(self):
        """The cache states 13 + (30-13)/17*(x-1) over 20 levels."""
        effect = rune_effects.resolve_rune("Waterwalking")
        assert effect.stat is rune_effects.RuneStat.ADAPTIVE_FORCE
        river = {"Waterwalking": {"in_river": 1}}
        assert effect.amount(_context(level=1, options=river)) == pytest.approx(13.0)
        assert effect.amount(_context(level=18, options=river)) == pytest.approx(30.0)
        assert effect.amount(_context(level=18)) == 0.0

    def test_the_option_defaults_off_and_the_flat_speed_is_withheld(self):
        option = sorcery.OPTIONS["Waterwalking"][0]
        assert option.key == "in_river"
        assert option.kind is rune_effects.RuneOptionKind.SWITCH
        assert option.default == 0.0
        assert option.bounds == (0.0, 1.0)
        effect = rune_effects.resolve_rune("Waterwalking")
        assert "'in_river' option says the holder is" in effect.disclosures[0]
        assert "movement speed as a percent" in effect.disclosures[1]

    def test_the_river_force_reaches_ability_power_through_rabadon_s(self):
        """23 force at level 11, taken as AP and multiplied by the hat."""
        request = _request(items=["Rabadon's Deathcap"], minor_runes=["Waterwalking"])
        dry = calculate_payload(dict(request))
        wet = calculate_payload(
            {**request, "rune_options": {"Waterwalking": {"in_river": 1}}}
        )
        assert dry["champion_stats"]["ability_power"] == 169
        assert wet["champion_stats"]["ability_power"] == 199
        assert dry["total_damage"] == pytest.approx(1886.1, abs=0.1)
        assert wet["total_damage"] == pytest.approx(2027.3, abs=0.1)


class TestGatheringStorm:
    """Sorcery row 3: adaptive force by the clock, one step every ten minutes."""

    def test_it_reads_the_minute_keyed_table_the_cache_states(self):
        """The cache states 4*m*(m-1): 0, 8, 24, 48, 80, 120, 168, 224."""
        effect = rune_effects.resolve_rune("Gathering Storm")
        assert effect.stat is rune_effects.RuneStat.ADAPTIVE_FORCE

        def at(minute):
            return effect.amount(
                _context(options={"Gathering Storm": {"game_minute": minute}})
            )

        assert [at(minute) for minute in (0, 10, 20, 30)] == [0.0, 8.0, 24.0, 48.0]
        assert at(70) == pytest.approx(224.0)
        # A minute inside a step reads that step, never an interpolation.
        assert at(25) == pytest.approx(24.0)

    def test_its_default_is_the_first_column_where_it_grants_nothing(self):
        effect = rune_effects.resolve_rune("Gathering Storm")
        assert effect.amount(_context()) == 0.0
        assert "minute 0 by default" in effect.disclosures[0]
        assert "'game_minute' option names" in effect.disclosures[0]
        assert "grows every 10 minutes" in effect.disclosures[1]

    def test_the_option_is_bounded_by_the_rune_s_own_table(self):
        option = sorcery.OPTIONS["Gathering Storm"][0]
        assert option.kind is rune_effects.RuneOptionKind.COUNT
        assert option.bounds == (0.0, 70.0)
        assert option.default == 0.0
        with pytest.raises(ValueError, match="between 0 and 70"):
            option.validated(80)

    def test_a_table_that_is_not_the_force_and_its_rendering_fails_closed(self):
        """Table 0 must be table 1 times Template:Adaptive's own conversion."""
        with pytest.raises(KeyError, match="attack-damage rendering"):
            sorcery.COMPILERS["Gathering Storm"](
                {
                    "effects": {
                        "leveling": [[0.0, 9.0], [0.0, 8.0]],
                        "minutes_range": [0.0, 10.0],
                    }
                }
            )

    def test_a_single_column_table_states_no_step_and_fails_closed(self):
        with pytest.raises(KeyError, match="needs at least two"):
            sorcery.COMPILERS["Gathering Storm"](
                {"effects": {"leveling": [[0.0], [0.0]], "minutes_range": [0.0, 10.0]}}
            )

    def test_the_clock_reaches_ability_power(self):
        """48 force at minute 30, taken as AP and multiplied by the hat."""
        request = _request(
            items=["Rabadon's Deathcap"], minor_runes=["Gathering Storm"]
        )
        early = calculate_payload(dict(request))
        late = calculate_payload(
            {**request, "rune_options": {"Gathering Storm": {"game_minute": 30}}}
        )
        assert early["champion_stats"]["ability_power"] == 169
        assert late["champion_stats"]["ability_power"] == 231
        assert early["total_damage"] == pytest.approx(1886.1, abs=0.1)
        assert late["total_damage"] == pytest.approx(2177.9, abs=0.1)

    def test_the_note_names_the_option_and_never_asserts_the_priced_minute(self):
        """A disclosure is compiled once; a set option must not make it a lie."""
        late = calculate_payload(
            _request(
                minor_runes=["Gathering Storm"],
                rune_options={"Gathering Storm": {"game_minute": 30}},
            )
        )
        note = next(note for note in late["notes"] if "Gathering Storm" in note)
        assert "'game_minute' option names" in note
        assert "is priced at game minute 0" not in note


class TestSorceryRefusals:
    """The two Sorcery runes whose halves this engine holds no channel for."""

    def test_manaflow_band_is_withheld_and_names_the_items_it_would_feed(self):
        effect = rune_effects.resolve_rune("Manaflow Band")
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "no rune stat channel carries mana" in effect.zero_policy.reason
        assert any("Muramana" in receipt for receipt in effect.receipts)

    def test_nimbus_cloak_is_withheld_because_the_fight_casts_no_summoner_spell(self):
        effect = rune_effects.resolve_rune("Nimbus Cloak")
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "the fight model casts none" in effect.zero_policy.reason

    def test_a_refusal_publishes_its_receipt_in_the_fight_notes(self):
        result = calculate_payload(_request(minor_runes=["Nimbus Cloak"]))
        assert any("Nimbus Cloak is not priced" in note for note in result["notes"])


class TestSorceryCoverage:
    def test_every_sorcery_minor_compiles(self):
        """All nine Sorcery minors compile; Axiom Arcanist rides the flat-amp kind."""
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        minors = [
            entry
            for entry in catalog.values()
            if entry["path"] == "Sorcery" and entry["row"]
        ]
        assert len(minors) == 9
        assert [entry["name"] for entry in minors if not entry["implemented"]] == []

    def test_the_declared_options_reach_the_catalog(self):
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        assert [option["key"] for option in catalog["Gathering Storm"]["options"]] == (
            ["game_minute"]
        )
        assert [option["key"] for option in catalog["Waterwalking"]["options"]] == (
            ["in_river"]
        )
        assert catalog["Gathering Storm"]["options"][0]["maximum"] == 70.0


class TestTheParseTheseRunesNeeded:
    """Two pp forms and one prose form the Sorcery minors are stated in."""

    def test_a_column_count_span_runs_x_over_the_columns_not_the_keys(self):
        """ "0 to 70 for 8" is eight columns; the formula's x is 1 through 8."""
        assert rune_parser.evaluate_pp("4*x*(x-1)", "0 to 70 for 8") == (
            [0.0, 8.0, 24.0, 48.0, 80.0, 120.0, 168.0, 224.0]
        )

    def test_an_unbounded_final_column_is_dropped_not_evaluated(self):
        assert rune_parser.evaluate_pp("4*x*(x-1);∞", "0 to 70 for 8;∞") == (
            rune_parser.evaluate_pp("4*x*(x-1)", "0 to 70 for 8")
        )

    def test_the_key_span_is_recorded_under_the_table_s_own_type(self):
        effects, warnings = rune_parser.parse_effects(
            "{{pp|4*x*(x-1);∞|0 to 70 for 8;∞|type=minutes}}"
        )
        assert effects["minutes_range"] == [0.0, 70.0]
        assert warnings == []

    def test_a_level_gated_grant_records_the_level_with_the_number(self):
        effects, _ = rune_parser.parse_effects(
            "* Level 5: + 5 [[ability haste]].\n* Level 8: + 5 [[ability haste]]."
        )
        assert effects["ability_haste_level_gates"] == [[5, 5.0], [8, 5.0]]
