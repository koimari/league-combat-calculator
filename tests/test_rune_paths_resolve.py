"""Resolve's minor runes: three priced runes and six receipted refusals.

Resolve is the durability path and the pair engine prices outgoing damage,
so six of its nine runes compile to a refusal that says which half this
engine holds no channel for. Three are not refusals: Overgrowth's stacks buy
maximum health, which the fight's stat block does read; Shield Bash prices
the swing a self-shield armed; and Font of Life heals on the casts that
impair, which is the impaired stream read from the impairing side.
"""

import pytest

from src.calculator import rune_effects, rune_parser
from src.calculator.calculate import calculate_payload
from src.calculator.item_effects import DamageInputs
from src.calculator.rune_paths import resolve

#: Every Resolve rune that books no damage, with the words its receipt must
#: carry — the reason is the receipt, so it is pinned per rune rather than
#: asserted as "some string".
REFUSALS = {
    "Demolish": "damages turrets",
    "Conditioning": "outgoing damage",
    "Second Wind": "carries neither the holder's health",
    "Bone Plating": "damage the holder receives",
    "Revitalize": "the rune stat block has no channel for that stat",
    "Unflinching": "while the holder is crowd controlled",
}


def _context(*, level=11, stacks=None):
    options = {"Overgrowth": {"stacks": stacks}} if stacks is not None else {}
    return rune_effects.RuneStatContext(
        level=level,
        is_melee=True,
        bonus_attack_damage=0.0,
        ability_power=0.0,
        options=options,
    )


def _request(**overrides):
    payload = {
        "champion": "Cho'Gath",
        "level": 11,
        "items": [],
        "fight_mode": "one_rotation",
    }
    payload.update(overrides)
    return payload


class TestOvergrowth:
    """Resolve row 3: permanent maximum health, one share per stack."""

    def test_it_grants_the_share_the_cache_states_per_stack(self):
        """The cache states 3 bonus health a stack, un-stacked by default."""
        effect = rune_effects.resolve_rune("Overgrowth")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.BONUS_HEALTH
        assert effect.amount(_context()) == 0.0
        assert effect.amount(_context(stacks=1)) == pytest.approx(3.0)
        assert effect.amount(_context(stacks=15)) == pytest.approx(45.0)

    def test_the_option_is_bounded_by_the_threshold_the_rune_names(self):
        """Its text states one count: after reaching 15 stacks."""
        option = resolve.OPTIONS["Overgrowth"][0]
        assert option.key == "stacks"
        assert option.kind is rune_effects.RuneOptionKind.COUNT
        assert option.default == 0.0
        assert option.bounds == (0.0, 15.0)
        with pytest.raises(ValueError, match="between 0 and 15"):
            option.validated(16)

    def test_the_percentage_half_is_disclosed_as_withheld(self):
        effect = rune_effects.resolve_rune("Overgrowth")
        assert "'stacks' option names" in effect.disclosures[0]
        assert "worth 3 maximum health" in effect.disclosures[0]
        assert "at 15 stacks" in effect.disclosures[1]
        assert "stacks indefinitely in game" in effect.disclosures[1]

    def test_a_record_with_no_threshold_bounds_nothing_and_fails_closed(self):
        with pytest.raises(KeyError, match="stack_threshold"):
            resolve.COMPILERS["Overgrowth"]({"effects": {"bonus_health": 3.0}})
        with pytest.raises(KeyError, match="bounds nothing"):
            resolve.COMPILERS["Overgrowth"](
                {"effects": {"bonus_health": 3.0, "stack_threshold": 0}}
            )

    def test_the_health_reaches_the_fight_and_health_scaling_damage_spends_it(self):
        """Cho'Gath's damage scales with his own maximum health."""
        bare = calculate_payload(_request())
        grown = calculate_payload(
            _request(
                minor_runes=["Overgrowth"],
                rune_options={"Overgrowth": {"stacks": 15}},
            )
        )
        assert bare["champion_stats"]["health"] == pytest.approx(2189.0)
        assert grown["champion_stats"]["health"] == pytest.approx(2234.0)
        assert bare["total_damage"] == pytest.approx(1058.5, abs=0.1)
        assert grown["total_damage"] == pytest.approx(1063.0, abs=0.1)

    def test_un_stacked_is_the_default_through_the_whole_pipeline(self):
        bare = calculate_payload(_request())
        selected = calculate_payload(_request(minor_runes=["Overgrowth"]))
        assert selected["champion_stats"]["health"] == (
            bare["champion_stats"]["health"]
        )
        assert selected["total_damage"] == pytest.approx(bare["total_damage"])


class TestResolveRefusals:
    """Six runes the pair engine holds no channel for, each saying which."""

    @pytest.mark.parametrize("name,reason", sorted(REFUSALS.items()))
    def test_each_refusal_is_withheld_and_names_the_half_it_refuses(self, name, reason):
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect), name
        assert effect.zero_policy.disposition.name == "WITHHELD", name
        assert reason in effect.zero_policy.reason, name
        assert effect.receipts[0].startswith(f"{name} is not priced:")

    def test_a_selected_refusal_publishes_its_receipt_and_moves_nothing(self):
        bare = calculate_payload(_request())
        with_rune = calculate_payload(_request(minor_runes=["Bone Plating"]))
        assert any("Bone Plating is not priced" in note for note in with_rune["notes"])
        assert with_rune["total_damage"] == pytest.approx(bare["total_damage"])


class TestResolveCoverage:
    def test_every_resolve_minor_compiles(self):
        catalog = [
            entry
            for entry in rune_effects.rune_catalog()
            if entry["path"] == "Resolve" and entry["row"]
        ]
        assert len(catalog) == 9
        assert all(entry["implemented"] is True for entry in catalog)

    def test_the_declared_option_reaches_the_catalog(self):
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        options = catalog["Overgrowth"]["options"]
        assert [option["key"] for option in options] == ["stacks"]
        assert options[0]["maximum"] == 15.0
        assert options[0]["default"] == 0.0


class TestTheParseOvergrowthNeeded:
    def test_a_stated_threshold_is_recorded_as_the_count_it_is(self):
        effects, warnings = rune_parser.parse_effects(
            "After reaching 15 stacks (120 monsters or minions), your health "
            "is permanently increased."
        )
        assert effects["stack_threshold"] == 15
        assert warnings == []


#: A twenty-second window with the auto stream on, so a self-shield has a
#: swing to arm. Malphite's passive shield rides his first damage event.
_SHIELD_PROBE = {
    "level": 18,
    "items": ["Sunfire Aegis"],
    "fight_mode": "time_based",
    "fight_duration": 20.0,
    "auto_attack_uptime_mode": "calculated",
    "target_health": 10000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}


class TestShieldBash:
    """The swing a self-shield armed, on the stream that watches for one."""

    def test_it_prices_its_level_table_and_its_bonus_health_share(self):
        """30 at level 18, plus 2.5% of the holder's bonus health."""
        effect = rune_effects.resolve_rune("Shield Bash")
        assert isinstance(effect, rune_effects.RuneProcEffect)
        assert effect.trigger is rune_effects.RuneTrigger.SELF_SHIELD_EVENTS
        assert effect.raw_damage(_shield_inputs(level=18)) == pytest.approx(30.0)
        assert effect.raw_damage(
            _shield_inputs(level=18, health=2500.0, base_health=2000.0)
        ) == pytest.approx(30.0 + 0.025 * 500.0)
        assert effect.raw_damage(_shield_inputs(level=1)) == pytest.approx(5.0)

    def test_both_ratios_come_out_of_the_cache_not_the_compiler(self):
        cached = rune_effects.RUNE_EFFECTS["Shield Bash"]["effects"]
        assert cached["bonus_health_ratio"] == 0.025
        assert cached["shield_amount_ratio"] == 0.15

    def test_the_shield_share_is_withheld_because_a_row_prices_one_number(self):
        effect = rune_effects.resolve_rune("Shield Bash")
        assert "15% of the shield's own amount — is withheld" in effect.disclosures[1]

    def test_a_shielded_kit_empowers_one_swing_and_an_unshielded_one_none(self):
        """Malphite's passive shield arms his first swing; Ashe has none.

        350 bonus health from Sunfire Aegis, so the raw is 30 + 8.75 =
        38.75, halved by 100 magic resistance to 19.4 — and the fight total
        moves by exactly that.
        """
        bare = calculate_payload({**_SHIELD_PROBE, "champion": "Malphite"})
        shielded = calculate_payload(
            {**_SHIELD_PROBE, "champion": "Malphite", "minor_runes": ["Shield Bash"]}
        )
        bonus_health = (
            bare["champion_stats"]["health"] - bare["champion_stats"]["base_health"]
        )
        assert bonus_health == pytest.approx(350.0)
        row = shielded["breakdown"]["rune_Shield Bash"]
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(19.4, abs=0.05)
        assert shielded["total_damage"] - bare["total_damage"] == pytest.approx(
            19.4, abs=0.05
        )

    def test_a_kit_with_no_self_shield_books_nothing_and_says_so(self):
        result = calculate_payload(
            {**_SHIELD_PROBE, "champion": "Ashe", "minor_runes": ["Shield Bash"]}
        )
        assert "rune_Shield Bash" not in result["breakdown"]
        assert any(
            "Shield Bash never procced: the simulated fight produced no basic "
            "attacks following a self-shield" in note
            for note in result["notes"]
        )

    def test_a_shield_with_no_swing_after_it_empowers_nothing(self):
        """Camille shields herself and this fight gives her no swing at all.

        The stream counts swings rather than shields for exactly this case:
        pricing the shield's own timestamp would book damage no attack
        delivered.
        """
        result = calculate_payload(
            {**_SHIELD_PROBE, "champion": "Camille", "minor_runes": ["Shield Bash"]}
        )
        assert "rune_Shield Bash" not in result["breakdown"]
        assert any("Shield Bash never procced" in note for note in result["notes"])


def _shield_inputs(*, level, health=0.0, base_health=0.0):
    return DamageInputs(
        champion_stats={"health": health, "base_health": base_health},
        level=level,
        is_melee=True,
        target_max_health=10000.0,
        target_current_health=10000.0,
    )


class TestFontOfLife:
    """A heal on the casts that impair — both channels meeting on one rune."""

    def test_it_heals_its_cached_melee_and_ranged_tables(self):
        """10 to 50 melee, 7 to 35 ranged, once per 20s."""
        effect = rune_effects.resolve_rune("Font of Life")
        assert isinstance(effect, rune_effects.RuneHealEffect)
        assert effect.trigger is rune_effects.RuneHealTrigger.IMPAIRING_INSTANCES
        assert effect.cooldown_seconds == 20.0
        assert effect.amount(_heal_inputs(level=1, is_melee=True)) == pytest.approx(
            10.0
        )
        assert effect.amount(_heal_inputs(level=18, is_melee=True)) == (
            pytest.approx(50.0)
        )
        assert effect.amount(_heal_inputs(level=1, is_melee=False)) == pytest.approx(
            7.0
        )
        assert effect.amount(_heal_inputs(level=18, is_melee=False)) == (
            pytest.approx(35.0)
        )

    def test_the_ally_half_is_still_withheld_and_says_why_twice(self):
        effect = rune_effects.resolve_rune("Font of Life")
        assert "ally half is withheld twice over" in effect.disclosures[1]

    @pytest.mark.parametrize(
        "champion,amount",
        [("Malphite", 50.0), ("Ashe", 35.0)],
    )
    def test_an_impairing_kit_heals_at_its_range_class(self, champion, amount):
        """Malphite's melee 50 and Ashe's ranged 35, at the impairing cast."""
        request = {**_IMPAIR_PROBE, "champion": champion}
        bare = calculate_payload(
            {key: value for key, value in request.items() if key != "minor_runes"}
        )
        healed = calculate_payload(dict(request))
        packets = [
            event
            for event in healed["self_healing_events"]
            if event["kind"] == "rune_proc"
        ]
        assert [(packet["source"], packet["amount"]) for packet in packets] == [
            ("Font of Life (rune)", pytest.approx(amount))
        ]
        assert healed["self_healing"] - bare["self_healing"] == pytest.approx(amount)
        assert healed["total_damage"] == pytest.approx(bare["total_damage"])

    def test_a_kit_that_reviews_no_control_heals_nothing(self):
        """Annie declares no ``MODULE_CC``, so nothing impairs and nothing pays."""
        healed = calculate_payload({**_IMPAIR_PROBE, "champion": "Annie"})
        assert not [
            event
            for event in healed["self_healing_events"]
            if event["kind"] == "rune_proc"
        ]


#: A twenty-second window with Font of Life on the page — long enough for
#: the impairing casts a kit makes, and one rune cooldown wide.
_IMPAIR_PROBE = {
    "level": 18,
    "items": [],
    "fight_mode": "time_based",
    "fight_duration": 20.0,
    "target_health": 10000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
    "minor_runes": ["Font of Life"],
}


def _heal_inputs(*, level, is_melee):
    return DamageInputs(
        champion_stats={},
        level=level,
        is_melee=is_melee,
        target_max_health=10000.0,
        target_current_health=10000.0,
    )
