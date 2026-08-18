"""Tests for the wiki rune-template parser.

Fixtures are verbatim ``Template:Rune data <name>`` wikitext pulled from
wiki.leagueoflegends.com (action=raw). The parser turns that text into the
``data/runes.json`` payload shape consumed by ``rune_effects``.
"""

import pytest

from src.calculator.rune_parser import (
    evaluate_pp,
    parse_cooldown,
    parse_effects,
    parse_rune_template,
    rune_payload,
)

ELECTROCUTE_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Electrocute|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Domination
|slot         = Keystone
|description  = {{sbc|Passive:}} Damaging {{tip|basic attacks}}, {{tip|abilities}}, [[Named item effect|item effects]], and [[summoner spell]]s, as well as the application of {{tip|crowd control}} and {{tip|damage over time}} effects, apply {{tip|stacks}} against enemy {{tip|champion|champions}}, up to one per {{tip|cast instance}} per champion. Applying 3 stacks to a target within a 3 second period causes them to be struck by lightning after a {{fd|0.25}}-second delay, dealing them {{pp|60 + 10 * x|1 to 20 by 1}} {{as|(+ 10% '''bonus''' AD)}} {{as|(+ 5% AP)}} of either {{as|physical|physical damage}} or {{as|magic damage}}.
|description2 = {{sbc|Variable Damage:}} This effect deals either {{as|physical|physical damage}} or {{as|magic damage}} depending on the damage contribution.
|cooldown     = 20
|caption      = {{quote|"We called them the Thunderlords."|''Rune caption''}}
}}"""

PRESS_THE_ATTACK_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Press the Attack|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Precision
|slot         = Keystone
|description  = {{sbc|Passive:}} {{tip|Basic attacks}} {{tip|on-hit}} against enemy {{tip|champion|champions}} apply a {{tip|stack}} for 4 seconds, refreshing on subsequent applications, expiring upon attacking a new champion, and stacking up to 3 times. The third stack consumes all stacks to deal {{pp|40 + (160-40)/17*(x-1)|1 to 20 by 1}} '''bonus''' {{tip|adaptive damage}} and grant you 8% increased damage against champions until 5 seconds after exiting [[combat status|combat]] with them.
|description2 = {{Tip data/Adaptive damage|pst2|description}}
|range        =
|cooldown     = {{tt|6|Starts after consuming a target's stacks}}
}}"""


FIRST_STRIKE_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|First Strike|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2022
|path         = Inspiration
|slot         = Keystone
|description  = {{sbc|Passive:}} Initiating [[combat]] with an enemy {{tip|champion}} within the first {{fd|0.25}} seconds of champion combat grants {{g|10}} and ''First Strike'' for 3 seconds, causing all of your {{tt|post-mitigation damage|Damage calculated after modifiers}} dealt against champions to deal {{as|7% '''bonus''' true damage}}. Afterwards, you are granted {{g|gold}} equal to {{rd|50%|35%}} of all '''bonus''' damage dealt within the duration.
|description2 = ''First Strike'' will be placed on full cooldown without activating its effects after being struck by an enemy champion before you strike them.
|range        =
|cooldown     = 25 to 15
}}"""


class TestParseRuneTemplate:
    def test_named_params_extracted(self):
        params = parse_rune_template(ELECTROCUTE_WIKITEXT)
        assert params["path"] == "Domination"
        assert params["slot"] == "Keystone"
        assert params["cooldown"] == "20"
        assert params["description"].startswith("{{sbc|Passive:}}")

    def test_multiline_values_and_trailing_braces_ignored(self):
        params = parse_rune_template(PRESS_THE_ATTACK_WIKITEXT)
        assert params["range"] == ""
        assert "Starts after consuming" in params["cooldown"]
        # The closing }} of the template must not leak into the last value.
        assert not params["caption"].endswith("}}") if "caption" in params else True


ARCANE_COMET_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Arcane Comet|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Sorcery
|slot         = Keystone
|description  = {{sbc|Passive:}} Dealing {{tip|ability damage}} or {{tip|pet damage}} to an enemy {{tip|champion}} hurls an ''Arcane Comet'' at their current location that lands after {{rutngt|0.8}}, dealing {{pp|15 + (100-15)/17*(x-1)|1 to 20 by 1}} {{as|(+ 10% '''bonus''' AD)}} {{as|(+ 5% AP)}} of either {{as|physical|physical damage}} or {{as|magic damage}} to enemies within a {{tip|er|icononly = true}} 140 radius upon impact. This damage is increased by {{pp|0 to 100 by 5|0 to 750|key=%|label1=units|type=distance the comet travelled|label=damage increase}}, up to a maximum of {{pp|15*2 + (200-30)/17*(x-1)|1 to 20 by 1}} {{as|(+ {{ap|10*2}}% '''bonus''' AD)}} {{as|(+ {{ap|5*2}}% AP)}} at maximum range.
|description2 = {{sbc|Variable Damage:}} This effect deals either {{as|physical|physical damage}} or {{as|magic damage}} depending on the damage contribution from your {{as|{{sti|attack damage}}}} and {{as|{{sti|ability power}}}} to the effect's damage formula.<ul><li>Greater '''bonus damage''' from the {{as|{{sti|AD ratio}}}} → {{as|Physical damage}}</li><li>Greater '''bonus damage''' from the {{as|{{sti|AP ratio}}}} → {{as|Magic damage}}</li></ul>If the damage contribution of {{as|{{sti|AD}}}} and {{as|{{sti|AP}}}} are zero or otherwise equal, the damage type defaults to {{as|magic damage}}.
|range        = Global
|cooldown     = {{pp|20 - (20-8)/17*(x-1)|1 to 20 by 1}}
}}"""


class TestEvaluatePp:
    def test_linear_formula_over_level_range(self):
        values = evaluate_pp("60 + 10 * x", "1 to 20 by 1")
        assert len(values) == 20
        assert values[0] == 70
        assert values[19] == 260

    def test_range_shorthand_formula_enumerates_its_own_values(self):
        # Template:pp's other sourced form: the first param is itself a
        # "start to stop by step" enumeration (Arcane Comet's distance
        # table), with the second param carrying the keys, not the range.
        values = evaluate_pp("0 to 100 by 5", "0 to 750")
        assert values == [float(v) for v in range(0, 105, 5)]

    def test_stepless_range_interpolates_endpoints_over_default_span(self):
        # "80 to 150" (Aftershock): the wiki's Module:Ability progression
        # linear-fills a stepless range to defaultSize = 18 columns, first
        # value at level 1 and last at level 18.
        values = evaluate_pp("80 to 150", None)
        assert len(values) == 18
        assert values[0] == 80.0
        assert values[1] == pytest.approx(80 + 70 / 17)
        assert values[17] == pytest.approx(150.0)

    def test_for_suffix_supplies_the_level_range(self):
        # "formula for N" (Guardian, Hail of Blades, ...) evaluates the
        # formula for x = 1..N — the module's `for x = 1, times` loop.
        values = evaluate_pp("9 + (30-9)/17*(x-1) for 20", None)
        assert len(values) == 20
        assert values[0] == 9.0
        assert values[17] == pytest.approx(30.0)
        assert values[19] == pytest.approx(9 + 21 / 17 * 19)

    def test_stepless_range_with_for_suffix_spans_that_count(self):
        # "A to B for N": endpoints anchored over exactly N values
        # (the module rewrites it as A + (B-A)/(times-1)*(x-1)).
        assert evaluate_pp("25 to 15 for 5", None) == pytest.approx(
            [25.0, 22.5, 20.0, 17.5, 15.0]
        )

    def test_descending_enumeration_counts_down(self):
        # Cooldowns shrink with level, so descending "by" enumerations
        # are a legitimate wiki form — never a silent empty list.
        assert evaluate_pp("25 to 15 by 5", None) == [25.0, 20.0, 15.0]

    def test_parenthesised_formula(self):
        values = evaluate_pp("40 + (160-40)/17*(x-1)", "1 to 20 by 1")
        assert values[0] == 40
        assert values[17] == pytest.approx(160)

    def test_semicolon_value_list(self):
        assert evaluate_pp("10;20;30", None) == [10, 20, 30]

    def test_rejects_unsafe_expressions(self):
        with pytest.raises(ValueError):
            evaluate_pp("__import__('os')", "1 to 20 by 1")


class TestParseCooldown:
    def test_plain_number(self):
        assert parse_cooldown("20") == 20.0

    def test_tt_wrapped_number(self):
        assert parse_cooldown("{{tt|6|Starts after consuming stacks}}") == 6.0

    def test_empty_returns_none(self):
        assert parse_cooldown("") is None

    def test_pp_template_evaluates_to_per_level_list(self):
        cooldowns = parse_cooldown("{{pp|20 - (20-8)/17*(x-1)|1 to 20 by 1}}")
        assert len(cooldowns) == 20
        assert cooldowns[0] == pytest.approx(20.0)
        assert cooldowns[17] == pytest.approx(8.0)
        assert cooldowns[19] == pytest.approx(20 - 12 / 17 * 19)

    def test_bare_scaling_text_still_returns_none(self):
        # "25 to 15" outside a pp template carries no level range; the
        # parser does not claim to read it — absence stays the honest value.
        assert parse_cooldown("25 to 15") is None

    def test_stepless_pp_cooldown_interpolates_the_default_span(self):
        # A stepless pp range linear-fills the wiki's default 18 columns,
        # endpoints anchored — same semantics as effect-side pp tables.
        cooldowns = parse_cooldown("{{pp|25 to 15}}")
        assert len(cooldowns) == 18
        assert cooldowns[0] == pytest.approx(25.0)
        assert cooldowns[17] == pytest.approx(15.0)

    def test_all_named_pp_body_returns_none(self):
        # A pp with no positional formula must degrade to None, not crash.
        assert parse_cooldown("{{pp|type=x}}") is None


class TestRunePayload:
    def test_electrocute_payload_complete(self):
        payload = rune_payload(
            "Electrocute", ELECTROCUTE_WIKITEXT, icon="http://x/e.png"
        )
        assert payload["name"] == "Electrocute"
        assert payload["path"] == "Domination"
        assert payload["slot"] == "Keystone"
        assert payload["cooldown"] == 20.0
        assert payload["icon"] == "http://x/e.png"
        effects = payload["effects"]
        assert effects["leveling"] == [[60 + 10 * level for level in range(1, 21)]]
        assert effects["bonus_ad_ratio"] == pytest.approx(0.10)
        assert effects["ap_ratio"] == pytest.approx(0.05)
        assert effects["stacks_required"] == 3
        assert effects["stack_window_seconds"] == 3.0
        assert effects["proc_delay_seconds"] == 0.25

    def test_press_the_attack_effects_complete(self):
        payload = rune_payload("Press the Attack", PRESS_THE_ATTACK_WIKITEXT)
        assert payload["path"] == "Precision"
        assert payload["cooldown"] == 6.0
        effects = payload["effects"]
        assert effects["leveling"][0][0] == 40
        assert effects["max_stacks"] == 3
        assert effects["stack_duration_seconds"] == 4.0
        assert effects["damage_amp_ratio"] == pytest.approx(0.08)
        # No Electrocute-style stack sentence: those keys must be absent,
        # never defaulted — rune_effects fails closed on missing keys.
        assert "stacks_required" not in effects
        assert "proc_delay_seconds" not in effects

    def test_electrocute_gains_no_press_the_attack_keys(self):
        effects = rune_payload("Electrocute", ELECTROCUTE_WIKITEXT)["effects"]
        assert "max_stacks" not in effects
        assert "stack_duration_seconds" not in effects
        assert "damage_amp_ratio" not in effects

    def test_plain_ad_ratio_not_misread_as_bonus(self):
        text = ELECTROCUTE_WIKITEXT.replace("10% '''bonus''' AD", "30% AD")
        effects = rune_payload("Electrocute", text)["effects"]
        assert "bonus_ad_ratio" not in effects
        assert effects["ad_ratio"] == pytest.approx(0.30)


class TestFirstStrikePayload:
    def test_first_strike_effects_complete(self):
        payload = rune_payload("First Strike", FIRST_STRIKE_WIKITEXT)
        assert payload["path"] == "Inspiration"
        # "25 to 15" is level-scaling text the cooldown parser does not
        # claim to read; absence (null) is the honest value.
        assert payload["cooldown"] is None
        effects = payload["effects"]
        assert effects["bonus_true_damage_ratio"] == pytest.approx(0.07)
        assert effects["buff_duration_seconds"] == 3.0
        assert effects["flat_gold"] == 10.0
        assert effects["gold_conversion_ratios"] == [
            pytest.approx(0.50),
            pytest.approx(0.35),
        ]
        # {{fd|0.25}} here is the initiation window, not a proc delay.
        assert "proc_delay_seconds" not in effects

    def test_electrocute_gains_no_first_strike_keys(self):
        effects = rune_payload("Electrocute", ELECTROCUTE_WIKITEXT)["effects"]
        assert "bonus_true_damage_ratio" not in effects
        assert "flat_gold" not in effects
        assert "gold_conversion_ratios" not in effects
        assert "buff_duration_seconds" not in effects


class TestArcaneCometPayload:
    def test_arcane_comet_payload_complete(self):
        payload = rune_payload("Arcane Comet", ARCANE_COMET_WIKITEXT)
        assert payload["path"] == "Sorcery"
        # The cooldown param is itself a pp leveling formula: 20s at
        # level 1 down to 8s at 18 (6.59s at the level-20 cap).
        assert payload["cooldown"][0] == pytest.approx(20.0)
        assert payload["cooldown"][17] == pytest.approx(8.0)
        assert len(payload["cooldown"]) == 20
        effects = payload["effects"]
        # Leveling keeps only the level-keyed tables: minimum damage and
        # maximum-range damage. The distance table is not leveling.
        assert effects["leveling"] == [
            [15 + (100 - 15) / 17 * (level - 1) for level in range(1, 21)],
            [30 + (200 - 30) / 17 * (level - 1) for level in range(1, 21)],
        ]
        assert effects["bonus_ad_ratio"] == pytest.approx(0.10)
        assert effects["ap_ratio"] == pytest.approx(0.05)
        # The comet lands 0.8s after the triggering cast ({{rutngt|0.8}}).
        assert effects["proc_delay_seconds"] == pytest.approx(0.8)
        # The travel-distance amp table: +0% to +100% over 0-750 units.
        assert effects["distance_scaling"] == {
            "values": [float(v) for v in range(0, 105, 5)],
            "distance_range": [0.0, 750.0],
        }
        # Every template in the description now parses — no warnings.
        assert "parse_warnings" not in payload

    def test_electrocute_gains_no_comet_keys(self):
        effects = rune_payload("Electrocute", ELECTROCUTE_WIKITEXT)["effects"]
        assert "distance_scaling" not in effects

    def test_second_distance_table_is_recorded_as_a_warning(self):
        # Like duplicate ratios: a silently-kept last table would be a
        # plausible-looking wrong number. The implementer must see it.
        text = ARCANE_COMET_WIKITEXT.replace(
            "at maximum range.",
            "at maximum range, plus {{pp|0 to 50 by 5|0 to 750|"
            "type=distance the comet travelled}} extra.",
        )
        payload = rune_payload("Arcane Comet", text)
        assert any(
            "distance_scaling" in warning for warning in payload["parse_warnings"]
        )


class TestConflictingDuplicatesFailClosed:
    def test_conflicting_ap_ratios_drop_the_key_with_a_warning(self):
        # Either value would be a plausible-looking wrong number; the key
        # is dropped so rune_effects fails closed on the absence.
        text = ELECTROCUTE_WIKITEXT.replace(
            "{{as|(+ 5% AP)}}", "{{as|(+ 5% AP)}} and a shield of {{as|(+ 40% AP)}}"
        )
        payload = rune_payload("Electrocute", text)
        assert "ap_ratio" not in payload["effects"]
        assert any("ap_ratio" in warning for warning in payload["parse_warnings"])

    def test_equal_re_matches_keep_the_value(self):
        # Summon Aery states its 10% bonus AD ratio twice (damage and
        # shield); identical values are one fact, not a conflict.
        effects, warnings = parse_effects(
            "pounce, dealing 10 {{as|(+ 10% '''bonus''' AD)}} damage, "
            "shielding them for 20 {{as|(+ 10% '''bonus''' AD)}}"
        )
        assert effects["bonus_ad_ratio"] == pytest.approx(0.10)
        assert not warnings

    def test_conflicting_split_pairs_drop_the_key(self):
        effects, warnings = parse_effects(
            "Gain {{as|{{rd|6%|4.8%}} '''bonus''' attack speed|as}} now and "
            "{{as|{{rd|10%|8%}} '''bonus''' attack speed|as}} later"
        )
        assert "attack_speed_ratios" not in effects
        assert any("attack_speed_ratios" in warning for warning in warnings)


LETHAL_TEMPO_AS_FRAGMENT = (
    "Gain {{as|{{rd|6%|{{ap|6*0.8}}%}} '''bonus''' attack speed|as}} for each "
    "stack, up to {{as|{{rd|36%|{{ap|36*0.8}}%}}|as}} at maximum stacks."
)


class TestMeleeRangedSplitClassification:
    """Each {{rd|X%|Y%}} pair lands under a key naming its quantity."""

    def test_attack_speed_pair_resolves_nested_arithmetic(self):
        # {{ap|6*0.8}} is the wiki's arithmetic template: ranged = 4.8%.
        effects, _ = parse_effects(LETHAL_TEMPO_AS_FRAGMENT)
        assert effects["attack_speed_ratios"] == [
            pytest.approx(0.06),
            pytest.approx(0.048),
        ]

    def test_maximum_restatements_are_derived_not_duplicates(self):
        # "up to ... at maximum stacks" restates per-stack × max — reading
        # it as a second attack-speed pair would drop the real one.
        effects, warnings = parse_effects(LETHAL_TEMPO_AS_FRAGMENT)
        assert "attack_speed_ratios" in effects
        assert not any("attack_speed_ratios" in warning for warning in warnings)

    def test_movement_speed_pair_via_ms_typed_wrapper(self):
        effects, _ = parse_effects(
            "grant {{as|{{rd|20%|15%}}|ms}} {{sti|{{as|'''bonus''' movement "
            "speed}}}} for 1 second"
        )
        assert effects["move_speed_ratios"] == [
            pytest.approx(0.20),
            pytest.approx(0.15),
        ]

    def test_movement_speed_pair_via_prose_wrapper(self):
        # Stormraider's Surge shape: untyped {{as|...}} naming the stat.
        effects, _ = parse_effects(
            "grants you {{as|{{rd|48%|36%}} '''bonus''' movement speed}} and "
            "50% {{tip|slow resist}} for 4 seconds"
        )
        assert effects["move_speed_ratios"] == [
            pytest.approx(0.48),
            pytest.approx(0.36),
        ]

    def test_heal_share_pair(self):
        effects, _ = parse_effects(
            "you also {{tip|heal}} for {{rd|8%|5%}} of the "
            "{{tt|post-mitigation damage|Damage calculated after modifiers}} "
            "dealt against enemy champions"
        )
        assert effects["heal_share_ratios"] == [
            pytest.approx(0.08),
            pytest.approx(0.05),
        ]

    def test_max_health_pairs_resolve_nested_fd(self):
        # Grasp of the Undying: every number sits inside {{fd|...}}.
        effects, warnings = parse_effects(
            "consumes all stacks to deal {{as|'''bonus''' magic damage}} equal "
            "to {{as|{{rd|{{fd|3.5}}%|{{fd|1.4}}%}} of your '''maximum''' "
            "health}}, {{tip|heal}} you for {{as|(+ {{rd|{{fd|1.3}}%|"
            "{{fd|0.52}}%}} of your '''maximum''' health)}}, and permanently "
            "grant you {{as|{{rd|5|2}} '''bonus''' health}}."
        )
        assert effects["max_health_damage_ratios"] == [
            pytest.approx(0.035),
            pytest.approx(0.014),
        ]
        assert effects["max_health_heal_ratios"] == [
            pytest.approx(0.013),
            pytest.approx(0.0052),
        ]
        assert not warnings

    def test_ratio_pairs_inside_as_ratio_wrappers(self):
        # Fleet Footwork: the AD/AP ratios are themselves melee/ranged split.
        effects, _ = parse_effects(
            "heal you for 10 {{as|(+ {{rd|10%|6%}} '''bonus''' AD)}} "
            "{{as|(+ {{rd|5%|3%}} AP)}}"
        )
        assert effects["bonus_ad_ratios"] == [
            pytest.approx(0.10),
            pytest.approx(0.06),
        ]
        assert effects["ap_ratios"] == [pytest.approx(0.05), pytest.approx(0.03)]

    def test_unclassified_pair_warns_and_records_nothing(self):
        effects, warnings = parse_effects(
            "some novel effect of {{rd|9%|7%}} of your armor"
        )
        assert effects == {}
        assert any("melee/ranged" in warning for warning in warnings)

    def test_flat_stack_and_health_pairs_are_not_ratios(self):
        # Counts and flat stat grants are recorded as stated, not /100.
        effects, _ = parse_effects(
            "Gain {{rd|2|1}} stacks for {{tip|basic damage}} {{tip|on-hit}}. "
            "It will permanently grant you {{as|{{rd|5|2}} '''bonus''' health}}."
        )
        assert effects["basic_damage_stacks"] == [2.0, 1.0]
        assert effects["permanent_bonus_health"] == [5.0, 2.0]

    def test_recurring_decimal_resolves_exactly(self):
        # Lethal Tempo's bolt amp: {{recurring|6}} overlines the repeating
        # digits, so ranged is 0.6̅6% = 2/3%, not 0.6%.
        effects, warnings = parse_effects(
            "upon arrival, increased by {{rd|1%|{{fd|0.6{{recurring|6}}%}}}} per "
            "{{as|1% '''bonus''' attack speed}}"
        )
        assert effects["damage_per_bonus_attack_speed_ratios"] == [
            pytest.approx(0.01),
            pytest.approx(2 / 300),
        ]
        assert not warnings


class TestMeleeRangedLeveling:
    def test_pp_true_pair_evaluates_both_level_tables(self):
        # Lethal Tempo's bolt: melee and ranged formulas, each "for 20".
        effects, warnings = parse_effects(
            "a bolt that deals them {{rd|9 + (30-9)/17*(x-1) for 20|"
            "6 + (24-6)/17*(x-1) for 20|pp=true}} '''bonus''' "
            "{{tip|adaptive damage}} upon arrival"
        )
        melee, ranged = effects["melee_ranged_leveling"]
        assert len(melee) == 20 and len(ranged) == 20
        assert melee[0] == 9.0
        assert melee[17] == pytest.approx(30.0)
        assert ranged[0] == 6.0
        assert ranged[17] == pytest.approx(24.0)
        assert not warnings

    def test_heal_colored_pair_lands_under_a_heal_named_key(self):
        # Fleet Footwork's heal carries color=heal — not damage leveling.
        effects, _ = parse_effects(
            "{{tip|heal}} you for {{rd|"
            "10+(120/17)*(x-1)*(0.7025+0.0175*(x-1)) for 20|"
            "10*0.6+((120*0.6)/17)*(x-1)*(0.7025+0.0175*(x-1)) for 20|"
            "color=heal|pp=true}}"
        )
        melee, ranged = effects["heal_melee_ranged_leveling"]
        assert "melee_ranged_leveling" not in effects
        assert melee[0] == pytest.approx(10.0)
        # Level 18: 10 + 120 × (0.7025 + 0.0175×17) = exactly 130.
        assert melee[17] == pytest.approx(130.0)
        assert ranged[0] == pytest.approx(6.0)
        assert ranged[17] == pytest.approx(78.0)


class TestAdaptiveForce:
    def test_adaptive_template_evaluates_per_level_force(self):
        # Conqueror: per-stack adaptive force, levels 1..20; the "up to ...
        # at maximum stacks" restatement (× 12) is derived, not a second
        # table.
        effects, warnings = parse_effects(
            "Each stack grants {{adaptive|1.8 + (4-1.8)/17*(x-1)|20}}, up to "
            "{{adaptive|1.8*12 + (4*12-1.8*12)/17*(x-1)|20}} at maximum "
            "stacks, at which you also {{tip|heal}} for {{rd|8%|5%}} of the "
            "{{tt|post-mitigation damage|after modifiers}} dealt"
        )
        force = effects["adaptive_force_leveling"]
        assert len(force) == 20
        assert force[0] == pytest.approx(1.8)
        assert force[17] == pytest.approx(4.0)
        assert force[19] == pytest.approx(1.8 + 2.2 / 17 * 19)
        assert effects["heal_share_ratios"] == [
            pytest.approx(0.08),
            pytest.approx(0.05),
        ]
        assert not warnings


class TestSoulDamage:
    def test_dark_harvest_base_and_per_soul(self):
        effects, _ = parse_effects(
            "deals 30 {{as|(+ 11 per Soul)}} {{as|(+ 10% '''bonus''' AD)}} "
            "{{as|(+ 5% AP)}} '''bonus''' {{tip|adaptive damage}}"
        )
        assert effects["base_damage"] == 30.0
        assert effects["damage_per_soul"] == 11.0
        assert effects["bonus_ad_ratio"] == pytest.approx(0.10)


class TestProseDelays:
    def test_pounce_delay_without_second_delay_suffix(self):
        # Summon Aery: the 0.45s damage pounce is the proc delay; the
        # 0.35s ally-shield leap must not shadow it.
        effects, _ = parse_effects(
            "signal ''Aery'' to pounce at them over {{fd|0.45}} seconds, "
            "dealing {{pp|10 + (40/17)*(x-1)|1 to 20 by 1}} damage. Shielding "
            "an ally signals ''Aery'' to leap to their side over {{fd|0.35}} "
            "seconds, {{tip|shield|shielding}} them"
        )
        assert effects["proc_delay_seconds"] == 0.45

    def test_burn_tick_interval(self):
        effects, _ = parse_effects(
            "a burn that deals {{pp|(3/2) + ((12/2)-(3/2))/17*(x-1) for 20|"
            "color=magic damage}} magic damage every {{fd|0.5}} seconds"
        )
        assert effects["tick_interval_seconds"] == 0.5
        assert effects["leveling"][0][0] == pytest.approx(1.5)
        assert effects["leveling"][0][17] == pytest.approx(6.0)


class TestNestedApWithNamedParamsStaysUnresolved:
    def test_deathfire_amped_ratios_do_not_conflict_with_base(self):
        # {{ap|7*1.75/2|round=3}} is a derived display value; resolving it
        # would collide with the base 3.5% ratio and drop the key.
        effects, _ = parse_effects(
            "{{as|(+ {{ap|7/2}}% '''bonus''' AD)}} {{as|(+ {{ap|2.5/2}}% AP)}} "
            "magic damage, later increased to {{as|(+ {{ap|7*1.75/2|round=3}}% "
            "'''bonus''' AD)}} {{as|(+ {{ap|2.5*1.75/2|round=3}}% AP)}} per tick"
        )
        assert effects["bonus_ad_ratio"] == pytest.approx(0.035)
        assert effects["ap_ratio"] == pytest.approx(0.0125)
