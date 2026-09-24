"""Resolve's minor runes: eight priced runes and one receipted refusal.

Resolve is the durability path and the pair engine prices outgoing damage,
so one of its nine runes compiles to a refusal that says which half this
engine holds no channel for. Eight are not refusals: Overgrowth's stacks buy
maximum health, which the fight's stat block does read; Shield Bash prices
the swing a self-shield armed; Font of Life heals on the casts that impair,
which is the impaired stream read from the impairing side; Conditioning
and Unflinching grant resistances, which a kit scaling off bonus armor or
bonus magic resistance spends on damage; Revitalize grants heal and shield
power, which every recovery the holder applies is multiplied by; and Second
Wind regenerates a share of missing health off an incoming hit and Bone
Plating takes a flat amount off the hits after one, both on the survival
walk, which is where the packets the holder receives are held.
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
    "Demolish": "no structure class for a turret to be",
}


def _context(*, level=11, stacks=None):
    options = {"Overgrowth": {"stacks": stacks}} if stacks is not None else {}
    return rune_effects.RuneStatContext(
        level=level,
        is_melee=True,
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


class TestSecondWindRegeneratesOffAnIncomingHit:
    """The rune that waited on a trigger, and the lane that already had one.

    Its refusal was right that no member of either rune trigger vocabulary
    fires on damage taken, and wrong that this meant there was nowhere to
    be paid: the survival walk holds the packets the holder RECEIVED and
    already arms Doran's Shield's regeneration window off one. What was
    missing was a rune kind that could be armed there and the two numbers,
    neither of which the cache carried.
    """

    def _fight(self, *, runes=(), items=(), duration=10, enemies_attack=True):
        return calculate_payload(
            {
                "champion": "Garen",
                "level": 18,
                "role": "top",
                "items": list(items),
                "boots": "",
                "enemies": [
                    {
                        "kind": "champion",
                        "champion": "Darius",
                        "level": 18,
                        "role": "top",
                    }
                ],
                "fight_duration": duration,
                "fight_mode": "time_based",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
                "enemies_attack": enemies_attack,
                "keystone": "Grasp of the Undying",
                "minor_runes": list(runes),
                "stat_shards": [],
            },
            deterministic=True,
        )

    @staticmethod
    def _healing(result):
        return float(result["combat"]["breakdown"][0]["healing_received"])

    def test_the_parser_reads_the_share_and_the_seconds(self):
        entry = rune_effects.RUNE_EFFECTS["Second Wind"]
        effects, _ = rune_parser.parse_rune_effects("Second Wind", entry["description"])
        assert effects == {
            "missing_health_regen_ratio": 0.04,
            "missing_health_regen_duration_seconds": 10.0,
        }
        assert entry["effects"] == effects

    def test_neither_rule_matches_another_rune(self):
        """Manaflow Band's missing share is mana, and must not match."""
        matched = {
            name
            for name, entry in rune_effects.RUNE_EFFECTS.items()
            if entry.get("description")
            and "missing_health_regen_ratio"
            in rune_parser.parse_rune_effects(name, entry["description"])[0]
        }
        assert matched == {"Second Wind"}

    def test_it_compiles_to_a_regeneration_window_carrying_both_numbers(self):
        effect = rune_effects.resolve_rune("Second Wind")
        assert isinstance(effect, rune_effects.RuneRegenerationEffect)
        assert effect.missing_health_ratio == pytest.approx(0.04)
        assert effect.duration_seconds == pytest.approx(10.0)
        assert effect.source == "Second Wind (rune)"

    def test_a_cache_stating_no_share_fails_closed(self):
        with pytest.raises(KeyError, match="regenerates nothing"):
            resolve.COMPILERS["Second Wind"](
                {
                    "effects": {
                        "missing_health_regen_ratio": 0.0,
                        "missing_health_regen_duration_seconds": 10.0,
                    }
                }
            )

    def test_the_holder_regenerates_only_once_it_has_been_hit(self):
        """The trigger, measured from both sides of it.

        The bare fight heals only through Garen's own Grasp proc at 4.18 s;
        the rune adds its regeneration on top once Darius has hit him.
        """
        bare = self._fight()
        held = self._fight(runes=["Second Wind"])
        assert self._healing(bare) == pytest.approx(30.6, abs=0.1)
        assert self._healing(held) - self._healing(bare) == pytest.approx(26.6, abs=0.1)

    def test_with_no_enemy_attacking_the_window_is_never_armed(self):
        """The control: the rune answers an incoming hit and nothing else.

        The holder's own recovery is not zero in a fight nobody swings
        back in, so the reading is against the same fight without the
        rune rather than against zero.
        """
        quiet = self._fight(enemies_attack=False)
        held = self._fight(runes=["Second Wind"], enemies_attack=False)
        assert self._healing(held) == pytest.approx(self._healing(quiet))

    def test_it_pays_beside_an_item_window_rather_than_replacing_one(self):
        """One holder, two declarations, two recoveries."""
        item_only = self._fight(items=["Doran's Shield"])
        both = self._fight(runes=["Second Wind"], items=["Doran's Shield"])
        assert self._healing(item_only) == pytest.approx(159.1, abs=0.1)
        assert self._healing(both) == pytest.approx(194.0, abs=0.1)

    def test_it_discloses_the_floor_and_the_cadence_it_chose(self):
        disclosures = " ".join(rune_effects.resolve_rune("Second Wind").disclosures)
        assert "this reading is a floor" in disclosures
        assert "no source states a regeneration cadence" in disclosures
        assert "damage a shield absorbs whole arms nothing" in disclosures


class TestBonePlatingTakesItsFlatCutOffIncomingHits:
    """The rune that waited on a channel's direction, priced on the walk.

    The item field its refusal pointed at is one number read off a target
    and applied to every packet. This rune arms on a hit, pays a counted
    few after it and then waits out a cooldown, which no target field has
    room for; the survival walk has all of it, because it holds the
    incoming packets in order with their times.
    """

    def _fight(self, *, runes=(), enemy_level=6, duration=10):
        return calculate_payload(
            {
                "champion": "Garen",
                "level": 18,
                "role": "top",
                "items": [],
                "boots": "",
                "enemies": [
                    {
                        "kind": "champion",
                        "champion": "Darius",
                        "level": enemy_level,
                        "role": "top",
                    }
                ],
                "fight_duration": duration,
                "fight_mode": "time_based",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
                "enemies_attack": True,
                "keystone": "Grasp of the Undying",
                "minor_runes": list(runes),
                "stat_shards": [],
            },
            deterministic=True,
        )

    def test_the_parser_reads_the_count_and_the_activation(self):
        effects, _ = rune_parser.parse_rune_effects(
            "Bone Plating", rune_effects.RUNE_EFFECTS["Bone Plating"]["description"]
        )
        assert effects["incoming_hits_reduced"] == 3
        assert effects["incoming_reduction_window_seconds"] == 1.5

    def test_it_compiles_with_its_level_table_and_all_three_clocks(self):
        effect = rune_effects.resolve_rune("Bone Plating")
        assert isinstance(effect, rune_effects.RunePlatingEffect)
        assert effect.hits == 3
        assert effect.window_seconds == pytest.approx(1.5)
        assert effect.cooldown_seconds == pytest.approx(55.0)
        assert effect.flat_by_level[0] == pytest.approx(30.0)
        assert effect.flat_by_level[17] == pytest.approx(60.0)

    def test_a_cache_stating_no_hits_fails_closed(self):
        entry = dict(rune_effects.RUNE_EFFECTS["Bone Plating"])
        entry["effects"] = {**entry["effects"], "incoming_hits_reduced": 0}
        with pytest.raises(KeyError, match="takes nothing off anything"):
            resolve.COMPILERS["Bone Plating"](entry)

    def test_it_lowers_the_damage_the_holder_takes(self):
        bare = self._fight()["combat"]["breakdown"][0]
        plated = self._fight(runes=["Bone Plating"])["combat"]["breakdown"][0]
        # The cut is the three reduced hits, 112.7, whatever the base.
        assert bare["health_damage"] == pytest.approx(680.0, abs=0.1)
        assert plated["health_damage"] == pytest.approx(567.2, abs=0.1)

    def test_it_buys_time_in_a_fight_the_holder_loses(self):
        """The other reading of the same reduction: a later death."""
        bare = self._fight(enemy_level=18)["combat"]["breakdown"][0]
        plated = self._fight(runes=["Bone Plating"], enemy_level=18)["combat"][
            "breakdown"
        ][0]
        assert bare["death_time"] == pytest.approx(4.399, abs=0.01)
        assert plated["death_time"] == pytest.approx(5.767, abs=0.01)

    def test_the_holder_s_own_damage_is_untouched(self):
        """The control: a defensive rune moves nothing the holder deals."""
        bare = self._fight()
        plated = self._fight(runes=["Bone Plating"])
        assert plated["total_damage"] == pytest.approx(bare["total_damage"])

    def test_it_discloses_the_arming_hit_and_the_one_enemy_it_cannot_read(self):
        disclosures = " ".join(rune_effects.resolve_rune("Bone Plating").disclosures)
        assert "The arming hit is not one of the reduced ones" in disclosures
        assert "reduces true damage too" in disclosures
        assert "which is a ceiling" in disclosures


class TestResolveRefusals:
    """The runes the pair engine holds no channel for, each saying which."""

    def test_the_table_is_exactly_the_module_s_own_refusal_set(self):
        """Derived, not hand-listed.

        The table above is only a parametrize source, so a rune leaving
        ``_NO_DAMAGE`` would drop out of the suite in silence and one added
        to it would never be checked. This is what makes a removal here a
        consequence of the module rather than a convenience: Conditioning
        left both in the same commit, when its resistances reached a channel.
        """
        assert set(REFUSALS) == set(resolve._NO_DAMAGE)

    @pytest.mark.parametrize(("name", "reason"), sorted(REFUSALS.items()))
    def test_each_refusal_is_withheld_and_names_the_half_it_refuses(self, name, reason):
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect), name
        assert effect.zero_policy.disposition.name == "WITHHELD", name
        assert reason in effect.zero_policy.reason, name
        assert effect.receipts[0].startswith(f"{name} is not priced:")

    def test_a_selected_refusal_publishes_its_receipt_and_moves_nothing(self):
        bare = calculate_payload(_request())
        with_rune = calculate_payload(_request(minor_runes=["Demolish"]))
        assert any("Demolish is not priced" in note for note in with_rune["notes"])
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
        ("champion", "amount"),
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
