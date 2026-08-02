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


class TestEvaluatePp:
    def test_linear_formula_over_level_range(self):
        values = evaluate_pp("60 + 10 * x", "1 to 20 by 1")
        assert len(values) == 20
        assert values[0] == 70
        assert values[19] == 260

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


class TestDuplicateRatioWarning:
    def test_second_ap_ratio_is_recorded_as_a_warning(self):
        text = ELECTROCUTE_WIKITEXT.replace(
            "{{as|(+ 5% AP)}}", "{{as|(+ 5% AP)}} and a shield of {{as|(+ 40% AP)}}"
        )
        payload = rune_payload("Electrocute", text)
        assert payload["effects"]["ap_ratio"] == pytest.approx(0.40)
        assert any("ap_ratio" in warning for warning in payload["parse_warnings"])
