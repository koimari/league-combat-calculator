"""Tests for the wiki rune-template parser.

Fixtures are verbatim ``Template:Rune data <name>`` wikitext pulled from
wiki.leagueoflegends.com (action=raw). The parser turns that text into the
``data/runes.json`` payload shape consumed by ``rune_effects``.
"""

import pytest

from src.calculator.rune_parser import (
    evaluate_pp,
    parse_cooldown,
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

    def test_stepless_range_is_not_an_enumeration(self):
        # "80 to 150" (Aftershock) means linear over an *implicit* level
        # span the template does not state — expanding it by 1 would
        # fabricate 71 plausible-looking wrong values. Refusal is honest.
        with pytest.raises(ValueError):
            evaluate_pp("80 to 150", None)

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

    def test_stepless_pp_scaling_returns_none(self):
        # First Strike's cooldown: a pp over an implicit level span the
        # template does not state. None, never an empty or wrong list.
        assert parse_cooldown("{{pp|25 to 15}}") is None

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
        assert effects["melee_ranged_ratios"] == [
            pytest.approx(0.50),
            pytest.approx(0.35),
        ]
        # {{fd|0.25}} here is the initiation window, not a proc delay.
        assert "proc_delay_seconds" not in effects

    def test_electrocute_gains_no_first_strike_keys(self):
        effects = rune_payload("Electrocute", ELECTROCUTE_WIKITEXT)["effects"]
        assert "bonus_true_damage_ratio" not in effects
        assert "flat_gold" not in effects
        assert "melee_ranged_ratios" not in effects
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


class TestDuplicateRatioWarning:
    def test_second_ap_ratio_is_recorded_as_a_warning(self):
        text = ELECTROCUTE_WIKITEXT.replace(
            "{{as|(+ 5% AP)}}", "{{as|(+ 5% AP)}} and a shield of {{as|(+ 40% AP)}}"
        )
        payload = rune_payload("Electrocute", text)
        assert payload["effects"]["ap_ratio"] == pytest.approx(0.40)
        assert any("ap_ratio" in warning for warning in payload["parse_warnings"])
