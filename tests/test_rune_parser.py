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


AERY_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Summon Aery|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Sorcery
|slot         = Keystone
|description  = {{sbc|Passive:}} Damaging {{tip|basic attacks}}, {{tip|abilities}}, and [[Named item effect|item effects]] against an enemy {{tip|champion}} signal ''Aery'' to pounce at them over {{fd|0.45}} seconds, dealing {{pp|10 + (40/17)*(x-1)|1 to 20 by 1}} {{as|(+ 10% '''bonus''' AD)}} {{as|(+ 5% AP)}} {{tip|adaptive damage}}. {{tip|Healing}}, {{tip|shield|shielding}}, or {{tip|buff|buffing}} an allied champion signals ''Aery'' to leap to their side over {{fd|0.35}} seconds, {{tip|shield|shielding}} them for {{pp|20 + (100-20)/17*(x-1)|1 to 20 by 1}} {{as|(+ 10% '''bonus''' AD)}} {{as|(+ 5% AP)}} for 2 seconds.
''Aery'' applies her effects to the affected champion upon arrival. She then lingers on the target for {{tt|2 seconds|Slightly less than this duration}} before flying back to the user, and cannot be sent out again until she returns.
|cooldown     =
}}"""


GRASP_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Grasp of the Undying|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Resolve
|slot         = Keystone
|description  = {{sbc|Passive:}} Entering [[Combat status|combat]] generates 1 [[stack]] every second for the next 3 seconds, refreshing the duration with each instance of combat and stacking the effect up to 4 times. At maximum stacks, your next [[basic attack]] {{tip|on-hit}} within 5 seconds against an enemy {{tip|champion}} consumes all stacks to deal {{as|'''bonus''' magic damage}} equal to {{as|{{rd|{{fd|3.5}}%|{{fd|1.4}}%}} of your '''maximum''' health}}, {{tip|heal}} you for {{as|(+ {{rd|{{fd|1.3}}%|{{fd|0.52}}%}} of your '''maximum''' health)}}, and permanently grant you {{as|{{rd|5|2}} '''bonus''' health}}.
|cooldown     =
}}"""


HAIL_OF_BLADES_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Hail of Blades|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Domination
|slot         = Keystone
|description  = {{sbc|Passive:}} Starting an {{tip|attack windup}} against an enemy {{tip|champion}} triggers ''Hail of Blades'', and if the windup completes, you gain 2 stacks of the effect for 3 seconds, with the duration refreshing on basic attacks {{tip|on-attack}} against enemy champions until all stacks are consumed. Stacks are consumed per basic attack on-attack and you generate an additional stack of the effect each time you activate an effect that has a {{tip|basic attack reset}}, up to 2 times.
While ''Hail of Blades'' is active, you gain {{as|{{rd|120%|60%}} {{sti|'''bonus''' attack speed}}|as}}, are allowed to exceed the {{tt|attack speed cap|normally 3.003 attacks per second}}, and basic attacks deal {{pp|4 + (20-4)/17*(x-1) for 20|color=true damage}} {{as|(+ 8% '''bonus''' AD)}} {{as|(+ 6% AP)}} {{as|{{sti|'''bonus true damage}}}}.<br><br>''The triggering attack benefits from Hail of Blades.''
|cooldown     = 10
}}"""


LETHAL_TEMPO_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Lethal Tempo|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2025
|path         = Precision
|slot         = Keystone
|description  = {{sbc|Passive:}} Basic attacks {{tip|on-attack}} against enemy {{tip|champion|champions}} grant a {{tip|stack}} for 6 seconds, refreshing on subsequent attacks and stacking up to 6 times. Gain {{as|{{rd|6%|{{ap|6*0.8}}%}} '''bonus''' attack speed|as}} for each stack, up to {{as|{{rd|36%|{{ap|36*0.8}}%}}|as}} at maximum stacks.
At maximum stacks, basic attacks are empowered to fire a bolt at the target {{tip|on-attack}} that deals them {{rd|9 + (30-9)/17*(x-1) for 20|6 + (24-6)/17*(x-1) for 20|pp=true}} '''bonus''' {{tip|adaptive damage}} upon arrival, increased by {{rd|1%|{{fd|0.6{{recurring|6}}%}}}} per {{as|1% '''bonus''' attack speed}}.
Stacks expire one by one every {{fd|0.5}} seconds when the duration ends.
|cooldown     =
}}"""


GLACIAL_AUGMENT_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Glacial Augment|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2022
|path         = Inspiration
|slot         = Keystone
|description  = {{sbc|Passive:}} {{tip|immobilize|Immobilizing}} an enemy {{tip|champion}} will cause 3 glacial rays to emanate from them towards you and other nearby enemy champions, creating icy zones with a 700 unit radius that last for 3 (+ 100% of the {{tt|immobilizing effect's duration|Duration after being modified by tenacity}}) seconds.
|description2 = Enemies within the icy zones, which have a width of 80 units, are {{tip|slow|slowed}} by 20% {{as|(+ 7% per 100 '''bonus''' AD)}} {{as|(+ 6% per 100 AP)}} {{as|(+ 9% per 10% heal and shield power)}} and have their damage reduced by 15% against your allies, excluding yourself.
|cooldown     = 25
}}"""


STORMRAIDER_SURGE_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Stormraider's Surge|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Sorcery
|slot         = Keystone
|description  = {{sbc|Passive:}} Dealing {{tt|damage|post-mitigation damage}} to an enemy champion equal to {{as|25% of their '''maximum''' health}} within 3 seconds grants you {{as|{{rd|48%|36%}} '''bonus''' movement speed}} and 50% {{tip|slow resist}} for 4 seconds.
|cooldown     = {{pp|20 to 10|1 to 20 by 1}}
}}"""


FLEET_FOOTWORK_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Fleet Footwork|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Precision
|slot         = Keystone
|description  = {{Unique|Energized|Moving and basic attacking generates ''Charges'', up to 100.}}
At 100 ''Charges'', become {{tip|Energized}}, empowering your next {{tip|basic attack}} to {{tip|heal}} you for {{rd|10+(120/17)*(x-1)*(0.7025+0.0175*(x-1)) for 20|10*0.6+((120*0.6)/17)*(x-1)*(0.7025+0.0175*(x-1)) for 20|color=heal|pp=true}} {{as|(+ {{rd|10%|6%}} '''bonus''' AD)}} {{as|(+ {{rd|5%|3%}} AP)}} and grant {{as|{{rd|20%|15%}}|ms}} {{sti|{{as|'''bonus''' movement speed}}}} for 1 second. Against {{tip|minion|minions}}, the healing is 15% effective.
|cooldown     =
}}"""


CONQUEROR_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Conqueror|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Precision
|slot         = Keystone
|description  = {{sbc|Passive:}} Dealing damage to enemy {{tip|champions}} generates {{tip|stacks}} of ''Conqueror'', lasting for 5 seconds, refreshing on subsequent damage against champions, and stacking up to 12 times. Gain {{rd|2|1}} stacks for {{tip|basic damage}} {{tip|on-hit}}. Otherwise, gain 2 stacks for any damage that is neither {{tip|basic damage|basic}} nor non-{{tip|pet damage|pet}} {{tip|proc damage}}, up to once every {{fd|4}} seconds per {{tip|cast instance}}.
Each stack of ''Conqueror'' grants {{adaptive|1.8 + (4-1.8)/17*(x-1)|20}}, up to {{adaptive|1.8*12 + (4*12-1.8*12)/17*(x-1)|20}} at maximum stacks, at which you also {{tip|heal}} for {{rd|8%|5%}} of the {{tt|post-mitigation damage|Damage calculated after modifiers}} dealt against enemy champions.
}}"""


DEATHFIRE_TOUCH_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Deathfire Touch|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Sorcery
|slot         = Keystone
|description  = Dealing {{tip|ability damage}} or {{tip|pet damage}} to enemy {{tip|champions}} inflicts a burn that deals {{pp|(3/2) + ((12/2)-(3/2))/17*(x-1) for 20|color=magic damage}} {{as|(+ {{ap|7/2}}% '''bonus''' AD)}} {{as|(+ {{ap|2.5/2}}% AP)}} {{as|magic damage}} every {{fd|0.5}} seconds over the duration. After the burn has lingered on a target for 3 seconds, its damage to them is increased{{ft|by 75%|to {{pp|(3*1.75/2) + ((12*1.75/2)-(3*1.75/2))/17*(x-1) for 20|color=magic damage}} {{as|(+ {{ap|7*1.75/2|round=3}}% '''bonus''' AD)}} {{as|(+ {{ap|2.5*1.75/2|round=3}}% AP)}} per tick}}while it lasts.
The burn's duration is based on the form of ability damage dealt to the target and is refreshed on subsequent applications:
* {{tip|Spell damage}}: 4 seconds.
* {{tip|Area damage}}: 2 seconds.
* {{tip|Persistent damage}}: 1 second.
* {{tip|Persistent area damage}}: 1 second.
* {{tip|Pet damage}}: 1 second.
|cooldown     =
}}"""


DARK_HARVEST_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Dark Harvest|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Domination
|slot         = Keystone
|description  = {{sbc|Passive:}} Dealing {{tip|pet damage|pet}} or non-{{tip|proc damage|proc}} damage against enemy {{tip|champions}} below {{as|50% of their '''maximum''' health}} deals 30 {{as|(+ 11 per Soul)}} {{as|(+ 10% '''bonus''' AD)}} {{as|(+ 5% AP)}} '''bonus''' {{tip|adaptive damage}} and, after a {{fd|1.75}}-second delay, reap {{as|1 Soul}}. This cannot occur again for 35 seconds, resetting to 1 second upon scoring a {{tip|takedown}} against an enemy champion.
|cooldown     = 35
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

    def test_formula_for_levels_supplies_the_level_span(self):
        values = evaluate_pp("50 + (165-50)/17*(x-1) for 20", None)
        assert len(values) == 20
        assert values[0] == pytest.approx(50)
        assert values[17] == pytest.approx(165)

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
            "Electrocute",
            ELECTROCUTE_WIKITEXT,
            icon="http://x/e.png",
            path="Domination",
            row=0,
        )
        assert payload["name"] == "Electrocute"
        assert payload["path"] == "Domination"
        assert payload["row"] == 0
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
        payload = rune_payload(
            "Press the Attack", PRESS_THE_ATTACK_WIKITEXT, path="Precision", row=0
        )
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

    def test_grasp_effects_keep_nested_melee_ranged_values(self):
        payload = rune_payload(
            "Grasp of the Undying", GRASP_WIKITEXT, path="Resolve", row=0
        )
        effects = payload["effects"]
        assert effects["grasp_damage_melee_ranged_ratios"] == pytest.approx(
            [0.035, 0.014]
        )
        assert effects["grasp_heal_melee_ranged_ratios"] == pytest.approx(
            [0.013, 0.0052]
        )
        assert effects["grasp_bonus_health_melee_ranged"] == [5.0, 2.0]
        assert effects["combat_stack_cadence_seconds"] == 1.0
        assert effects["combat_stack_generation_seconds"] == 3.0
        assert effects["max_stacks"] == 4
        assert effects["ready_window_seconds"] == 5.0
        assert (
            not {
                "max_health_damage_ratios",
                "max_health_heal_ratios",
                "permanent_bonus_health",
            }
            & effects.keys()
        )

    def test_grasp_patterns_do_not_leak_to_another_named_rune(self):
        payload = rune_payload("Not Grasp", GRASP_WIKITEXT, path="Resolve", row=0)
        assert not any(key.startswith("grasp_") for key in payload["effects"])

    def test_hail_of_blades_effects_keep_temporary_window_values(self):
        payload = rune_payload(
            "Hail of Blades", HAIL_OF_BLADES_WIKITEXT, path="Domination", row=0
        )
        effects = payload["effects"]
        assert effects["leveling"][0][0] == pytest.approx(4.0)
        assert effects["leveling"][0][17] == pytest.approx(20.0)
        assert effects["bonus_ad_ratio"] == pytest.approx(0.08)
        assert effects["ap_ratio"] == pytest.approx(0.06)
        assert effects["hail_bonus_attack_speed_melee_ranged"] == [120.0, 60.0]
        assert effects["hail_initial_stacks"] == 2
        assert effects["hail_stack_duration_seconds"] == pytest.approx(3.0)
        assert effects["hail_reset_stack_limit"] == 2
        assert "parse_warnings" not in payload

    def test_lethal_tempo_effects_keep_stacks_speed_bolts_and_expiry(self):
        payload = rune_payload(
            "Lethal Tempo", LETHAL_TEMPO_WIKITEXT, path="Precision", row=0
        )
        effects = payload["effects"]
        assert effects[
            "lethal_tempo_attack_speed_percent_melee_ranged"
        ] == pytest.approx([6.0, 4.8])
        assert effects["lethal_tempo_bolt_damage_melee_by_level"][0] == pytest.approx(
            9.0
        )
        assert effects["lethal_tempo_bolt_damage_melee_by_level"][17] == pytest.approx(
            30.0
        )
        assert effects["lethal_tempo_bolt_damage_ranged_by_level"][17] == pytest.approx(
            24.0
        )
        assert effects[
            "lethal_tempo_bolt_damage_increase_ratio_melee_ranged"
        ] == pytest.approx([0.01, 1.0 / 150.0])
        assert effects["max_stacks"] == 6
        assert effects["lethal_tempo_stack_duration_seconds"] == pytest.approx(6.0)
        assert effects["lethal_tempo_expiry_step_seconds"] == pytest.approx(0.5)
        assert "parse_warnings" not in payload

    def test_glacial_augment_effects_keep_zone_and_reduction_values(self):
        payload = rune_payload(
            "Glacial Augment", GLACIAL_AUGMENT_WIKITEXT, path="Inspiration", row=0
        )
        assert payload["cooldown"] == pytest.approx(25.0)
        effects = payload["effects"]
        assert effects["glacial_ray_count"] == 3
        assert effects["glacial_zone_radius_units"] == pytest.approx(700.0)
        assert effects["glacial_zone_width_units"] == pytest.approx(80.0)
        assert effects["glacial_zone_base_duration_seconds"] == pytest.approx(3.0)
        assert effects["glacial_zone_duration_cc_ratio"] == pytest.approx(1.0)
        assert effects["glacial_slow_base_ratio"] == pytest.approx(0.20)
        assert effects["glacial_slow_bonus_ad_ratio_per_100"] == pytest.approx(0.07)
        assert effects["glacial_slow_ap_ratio_per_100"] == pytest.approx(0.06)
        assert effects["glacial_slow_heal_shield_ratio_per_10"] == pytest.approx(0.09)
        assert effects["glacial_damage_reduction_ratio"] == pytest.approx(0.15)
        assert "parse_warnings" not in payload

    def test_stormraider_effects_keep_damage_window_and_movement_values(self):
        payload = rune_payload(
            "Stormraider's Surge", STORMRAIDER_SURGE_WIKITEXT, path="Sorcery", row=0
        )
        assert payload["cooldown"][0] == pytest.approx(20.0)
        assert payload["cooldown"][17] == pytest.approx(10.0)
        assert payload["cooldown"][19] == pytest.approx(8.8235294118)
        effects = payload["effects"]
        assert effects["stormraider_damage_threshold_ratio"] == pytest.approx(0.25)
        assert effects["stormraider_damage_window_seconds"] == pytest.approx(3.0)
        assert effects["stormraider_duration_seconds"] == pytest.approx(4.0)
        assert effects["stormraider_bonus_move_speed_melee_ranged"] == [48.0, 36.0]
        assert effects["stormraider_slow_resist_ratio"] == pytest.approx(0.50)
        assert "parse_warnings" not in payload

    def test_fleet_footwork_effects_keep_charge_heal_and_speed_values(self):
        payload = rune_payload(
            "Fleet Footwork", FLEET_FOOTWORK_WIKITEXT, path="Precision", row=0
        )
        effects = payload["effects"]
        assert effects["fleet_heal_melee_by_level"][0] == pytest.approx(10.0)
        assert effects["fleet_heal_melee_by_level"][17] == pytest.approx(130.0)
        assert effects["fleet_heal_ranged_by_level"][17] == pytest.approx(78.0)
        assert effects["fleet_bonus_ad_ratio_melee_ranged"] == [0.10, 0.06]
        assert effects["fleet_ap_ratio_melee_ranged"] == [0.05, 0.03]
        assert effects["fleet_bonus_move_speed_melee_ranged"] == [20.0, 15.0]
        assert effects["fleet_move_speed_duration_seconds"] == pytest.approx(1.0)
        assert effects["fleet_minion_heal_effectiveness"] == pytest.approx(0.15)
        assert effects["fleet_charge_cap"] == pytest.approx(100.0)

    def test_conqueror_effects_keep_force_stack_and_heal_values(self):
        payload = rune_payload("Conqueror", CONQUEROR_WIKITEXT, path="Precision", row=0)
        effects = payload["effects"]
        assert effects["conqueror_adaptive_force_by_level"][0] == pytest.approx(1.8)
        assert effects["conqueror_adaptive_force_by_level"][17] == pytest.approx(4.0)
        assert effects["conqueror_adaptive_force_max_by_level"][17] == pytest.approx(
            48.0
        )
        assert effects["conqueror_heal_melee_ranged_ratios"] == [0.08, 0.05]
        assert effects["conqueror_stack_duration_seconds"] == pytest.approx(5.0)
        assert effects["conqueror_cast_instance_interval_seconds"] == pytest.approx(4.0)
        assert effects["conqueror_stacks_per_application"] == 2
        assert effects["max_stacks"] == 12
        assert "parse_warnings" not in payload

    def test_deathfire_effects_keep_burn_states_and_duration_categories(self):
        payload = rune_payload(
            "Deathfire Touch", DEATHFIRE_TOUCH_WIKITEXT, path="Sorcery", row=0
        )
        effects = payload["effects"]
        assert effects["leveling"][0][0] == pytest.approx(1.5)
        assert effects["leveling"][0][17] == pytest.approx(6.0)
        assert effects["leveling"][1][17] == pytest.approx(10.5)
        assert effects["deathfire_bonus_ad_ratios_by_state"] == pytest.approx(
            [0.035, 0.06125]
        )
        assert effects["deathfire_ap_ratios_by_state"] == pytest.approx(
            [0.0125, 0.021875]
        )
        assert effects["deathfire_tick_interval_seconds"] == pytest.approx(0.5)
        assert effects["deathfire_amp_delay_seconds"] == pytest.approx(3.0)
        assert effects["deathfire_amp_ratio"] == pytest.approx(0.75)
        assert effects["deathfire_duration_seconds"] == {
            "spell_damage": 4.0,
            "area_damage": 2.0,
            "persistent_damage": 1.0,
            "persistent_area_damage": 1.0,
            "pet_damage": 1.0,
        }
        assert "parse_warnings" not in payload

    def test_electrocute_gains_no_press_the_attack_keys(self):
        effects = rune_payload(
            "Electrocute", ELECTROCUTE_WIKITEXT, path="Domination", row=0
        )["effects"]
        assert "max_stacks" not in effects
        assert "stack_duration_seconds" not in effects
        assert "damage_amp_ratio" not in effects

    def test_plain_ad_ratio_not_misread_as_bonus(self):
        text = ELECTROCUTE_WIKITEXT.replace("10% '''bonus''' AD", "30% AD")
        effects = rune_payload("Electrocute", text, path="Domination", row=0)["effects"]
        assert "bonus_ad_ratio" not in effects
        assert effects["ad_ratio"] == pytest.approx(0.30)


class TestFirstStrikePayload:
    def test_first_strike_effects_complete(self):
        payload = rune_payload(
            "First Strike", FIRST_STRIKE_WIKITEXT, path="Inspiration", row=0
        )
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
        effects = rune_payload(
            "Electrocute", ELECTROCUTE_WIKITEXT, path="Domination", row=0
        )["effects"]
        assert "bonus_true_damage_ratio" not in effects
        assert "flat_gold" not in effects
        assert "gold_conversion_ratios" not in effects
        assert "buff_duration_seconds" not in effects


class TestArcaneCometPayload:
    def test_arcane_comet_payload_complete(self):
        payload = rune_payload(
            "Arcane Comet", ARCANE_COMET_WIKITEXT, path="Sorcery", row=0
        )
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


class TestSummonAeryPayload:
    def test_aery_payload_keeps_damage_shield_and_linger_timings_separate(self):
        payload = rune_payload("Summon Aery", AERY_WIKITEXT, path="Sorcery", row=0)
        effects = payload["effects"]
        assert effects["damage_flight_seconds"] == pytest.approx(0.45)
        assert effects["shield_flight_seconds"] == pytest.approx(0.35)
        assert effects["shield_duration_seconds"] == pytest.approx(2.0)
        assert effects["linger_seconds"] == pytest.approx(2.0)
        assert effects["leveling"][0][0] == pytest.approx(10.0)
        assert effects["leveling"][1][0] == pytest.approx(20.0)
        # Every template in the description now parses — no warnings.
        assert "parse_warnings" not in payload


class TestDarkHarvestPayload:
    def test_dark_harvest_payload_keeps_threshold_and_soul_formula(self):
        payload = rune_payload(
            "Dark Harvest", DARK_HARVEST_WIKITEXT, path="Domination", row=0
        )
        effects = payload["effects"]
        assert effects["base_damage"] == pytest.approx(30.0)
        assert effects["soul_damage"] == pytest.approx(11.0)
        assert effects["health_threshold_ratio"] == pytest.approx(0.50)
        assert effects["proc_delay_seconds"] == pytest.approx(1.75)
        assert effects["takedown_reset_seconds"] == pytest.approx(1.0)
        assert "parse_warnings" not in payload

    def test_dark_harvest_patterns_do_not_leak_to_another_named_rune(self):
        payload = rune_payload(
            "Not Dark Harvest", DARK_HARVEST_WIKITEXT, path="Domination", row=0
        )
        effects = payload["effects"]
        assert "soul_damage" not in effects
        assert "health_threshold_ratio" not in effects
        assert "takedown_reset_seconds" not in effects


GUARDIAN_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Guardian|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Resolve
|slot         = Keystone
|description  = {{sbc|Passive:}} While within 350 units of an allied {{tip|champion}}, you raise your ''Guard''. If you or a ''Guarded'' ally would take {{pp|50 + (165-50)/17*(x-1) for 20}} damage within {{fd|2.5}} seconds or lethal damage, you both gain a {{tip|shield}} for {{pp|40 + (150-40)/17*(x-1) for 20}} {{as|(+ 20% of your AP)}} {{as|(+ 6% of your '''bonus''' health)}} for 2 seconds.
|description3 = ''Guardian'' only goes on {{sti|cooldown}} when the shield is triggered.
|range        = 350 / {{tt|Global|Targeted Guard}}
|cooldown     = {{pp|75 + (40-75)/17*(x-1) for 20}}
}}"""


AFTERSHOCK_WIKITEXT = """{{{{{1<noinclude>|Rune data</noinclude>}}}|Aftershock|{{{2|}}}|{{{3|}}}|{{{4|}}}|{{{5|}}}
|released     = Season 2018
|path         = Resolve
|slot         = Keystone
|description  = {{sbc|Passive:}} {{tip|Immobilize|Immobilizing}} an enemy {{tip|champion}} grants you a static {{as|45|armor}} {{as|(+ 75% '''bonus''' armor)}} {{as|'''bonus''' armor}} and {{as|45|mr}} {{as|(+ 75% '''bonus''' magic resistance)}} {{as|'''bonus''' magic resistance}} for {{fd|2.5}} seconds. The '''bonus''' resistances are each capped at {{pp|80 to 150}}. After the duration, you release a shockwave that deals {{as|{{pp|25 to 120}}|magic damage}} {{as|(+ 8% of your '''bonus''' health)}} {{as|magic damage}} to enemy champions and {{tip|monster|monsters}} within a {{tip|cr|icononly=true}} 350 radius.
|cooldown     = 20
}}"""


class TestAftershockPayload:
    def test_aftershock_payload_expands_implicit_level_tables(self):
        payload = rune_payload("Aftershock", AFTERSHOCK_WIKITEXT, path="Resolve", row=0)
        effects = payload["effects"]
        assert payload["cooldown"] == pytest.approx(20.0)
        assert effects["leveling"][0][0] == pytest.approx(80.0)
        assert effects["leveling"][0][17] == pytest.approx(150.0)
        assert effects["leveling"][1][0] == pytest.approx(25.0)
        assert effects["leveling"][1][17] == pytest.approx(120.0)
        assert effects["flat_armor"] == pytest.approx(45.0)
        assert effects["flat_magic_resistance"] == pytest.approx(45.0)
        assert effects["bonus_armor_ratio"] == pytest.approx(0.75)
        assert effects["bonus_magic_resistance_ratio"] == pytest.approx(0.75)
        assert effects["bonus_health_ratio"] == pytest.approx(0.08)
        assert effects["resistance_duration_seconds"] == pytest.approx(2.5)
        assert effects["shockwave_radius"] == pytest.approx(350.0)
        assert "parse_warnings" not in payload


class TestGuardianPayload:
    def test_guardian_payload_keeps_threshold_window_and_shield_scaling(self):
        payload = rune_payload("Guardian", GUARDIAN_WIKITEXT, path="Resolve", row=0)
        effects = payload["effects"]
        assert effects["trigger_window_seconds"] == pytest.approx(2.5)
        assert effects["shield_duration_seconds"] == pytest.approx(2.0)
        assert effects["ap_ratio"] == pytest.approx(0.20)
        assert effects["bonus_health_ratio"] == pytest.approx(0.06)
        assert len(effects["leveling"]) == 2
        assert payload["cooldown"][0] == pytest.approx(75.0)
        assert payload["cooldown"][17] == pytest.approx(40.0)
        assert "parse_warnings" not in payload

    def test_description_numbering_keeps_all_sourced_prose(self):
        payload = rune_payload("Guardian", GUARDIAN_WIKITEXT, path="Resolve", row=0)
        assert "only goes on" in payload["description"]

    def test_electrocute_gains_no_comet_keys(self):
        effects = rune_payload(
            "Electrocute", ELECTROCUTE_WIKITEXT, path="Domination", row=0
        )["effects"]
        assert "distance_scaling" not in effects

    def test_second_distance_table_is_recorded_as_a_warning(self):
        # Like duplicate ratios: a silently-kept last table would be a
        # plausible-looking wrong number. The implementer must see it.
        text = ARCANE_COMET_WIKITEXT.replace(
            "at maximum range.",
            "at maximum range, plus {{pp|0 to 50 by 5|0 to 750|"
            "type=distance the comet travelled}} extra.",
        )
        payload = rune_payload("Arcane Comet", text, path="Sorcery", row=0)
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
        payload = rune_payload("Electrocute", text, path="Domination", row=0)
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
        assert len(melee) == 20
        assert len(ranged) == 20
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


class TestPiecewiseProgressions:
    """Module:Ability progression's ``start; then +f(x) for N; …`` form.

    Two runes state a per-level payout this way, and both used to arrive as
    a parse warning. Each run continues from the previous run's last value,
    which is what makes ``1; then +0.25*x for 4`` a ramp rather than four
    independent values.
    """

    def test_absorb_life_s_progression_matches_the_wiki_s_own_prose(self):
        """The template states the rule twice; both readings must agree.

        The machine formula is ``1; then +0.25*x for 4; then +1*x for 5;
        then +2*x`` and the ``formula=`` prose beside it reads "1, +0.25 per
        level until level 5, then +1 per level until level 10, then +2 per
        level". The page's own span is "1 – 27 (based on level)".
        """
        values = evaluate_pp(
            "1; then +0.25*x for 4;then +1*x for 5; then +2*x", "1 to 20 by 1"
        )
        assert len(values) == 20
        assert values[:5] == pytest.approx([1.0, 1.25, 1.5, 1.75, 2.0])
        assert values[5:10] == pytest.approx([3.0, 4.0, 5.0, 6.0, 7.0])
        assert values[10] == pytest.approx(9.0)
        assert (values[17], values[19]) == (pytest.approx(23.0), pytest.approx(27.0))

    def test_a_run_states_its_length_and_the_last_one_takes_the_rest(self):
        assert evaluate_pp("10; then +5*x for 2; then +1*x", "1 to 5 by 1") == (
            pytest.approx([10.0, 15.0, 20.0, 21.0, 22.0])
        )

    def test_a_run_with_neither_a_length_nor_a_place_at_the_end_takes_one(self):
        assert evaluate_pp("1; then +2; then +3*x", "1 to 4 by 1") == pytest.approx(
            [1.0, 3.0, 6.0, 9.0]
        )

    def test_runs_that_do_not_fill_the_table_are_refused_not_truncated(self):
        """A silently short level table is the degradation to catch."""
        with pytest.raises(ValueError, match="renders 3 columns and its table has 5"):
            evaluate_pp("1; then +1*x for 2", "1 to 5 by 1")
        with pytest.raises(ValueError, match="overruns its 2-column table"):
            evaluate_pp("1; then +1*x for 4; then +2*x", "1 to 2 by 1")

    def test_a_semicolon_value_list_is_still_a_value_list(self):
        """``then`` is the marker, so nothing else changes shape."""
        assert evaluate_pp("10;20;30", None) == [10, 20, 30]
