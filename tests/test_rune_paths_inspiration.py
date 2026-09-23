"""Inspiration's minor runes: five stat grants and four receipted refusals.

Inspiration buys biscuits, boots, elixirs, summoner-spell swaps and gold
back. One of its runes has no combat number in any source and is an exact
zero; three have one this engine cannot reach and are withheld. Five grant
a stat: Jack Of All Trades, whose stacks are the build's own item stat types
and whose two channels are granted together, Approach Velocity, whose
movement speed reaches damage through Swiftmarch's conversion behind a
switch for the position the request does not carry, Magical Footwear, whose
flat boots grant rides the same conversion with no gate to ask for, Cosmic
Insight, whose item haste shortens the empowered-auto stream's own cooldown,
and Biscuit Delivery, whose permanent maximum health is kept per biscuit the
request says was consumed.
"""

import json
from pathlib import Path

import pytest

from src.calculator import rune_effects
from src.calculator.calculate import calculate_payload
from src.calculator.item_stat_block import item_stat_type_count
from src.calculator.rune_parser import parse_rune_effects

_RUNES = json.loads(Path("data/runes.json").read_text(encoding="utf-8"))

#: Every refused Inspiration rune, its disposition, and the words its receipt
#: must carry. A structural zero is "nothing to price"; a withheld rune is a
#: real number this engine has no channel for.
DISPOSITIONS = {
    "Hextech Flashtraption": ("STRUCTURAL_ZERO", "no source states a combat number"),
    "Cash Back": ("STRUCTURAL_ZERO", "gold never joins the fight's damage total"),
    "Triple Tonic": ("WITHHELD", "prices no consumable"),
    "Time Warp Tonic": ("WITHHELD", "the fight model consumes no potions"),
}


def _biscuits(consumed):
    """A context carrying one Biscuit Delivery count and nothing else."""
    return rune_effects.RuneStatContext(
        level=18,
        is_melee=True,
        options={"Biscuit Delivery": {"biscuits_consumed": consumed}},
    )


def _request(**overrides):
    payload = {
        "champion": "Ahri",
        "level": 11,
        "items": ["Rabadon's Deathcap"],
        "fight_mode": "time_based",
        "fight_duration": 20.0,
    }
    payload.update(overrides)
    return payload


class TestEveryInspirationRuneIsCompiledAndReceipted:
    @pytest.mark.parametrize(("name", "declaration"), sorted(DISPOSITIONS.items()))
    def test_it_books_no_damage_and_says_why(self, name, declaration):
        disposition, reason = declaration
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect), name
        assert effect.zero_policy.disposition.name == disposition, name
        assert reason in effect.zero_policy.reason, name

    def test_a_structural_zero_and_a_withheld_rune_read_differently(self):
        """The verdict is the disposition's, and the two are not the same claim."""
        exact = rune_effects.resolve_rune("Cash Back")
        refused = rune_effects.resolve_rune("Triple Tonic")
        assert exact.receipts[0].startswith("Cash Back deals no damage in any fight:")
        assert refused.receipts[0].startswith("Triple Tonic is not priced:")


class TestMagicalFootwearPricesItsBootsGrant:
    """The flat half of a split rune: boots on a clock stay withheld, the
    +10 flat bonus movement speed rides the flat channel.

    Its old receipt said the engine "reads no movement speed in any damage
    row". True of a damage row, false of the build: Swiftmarch converts the
    holder's total movement speed into adaptive force, so the no-Swiftmarch
    control below is the proof the mechanism names rather than implies.
    """

    def test_the_parser_reads_the_flat_grant_into_the_cached_effects(self):
        effects, _ = parse_rune_effects(
            "Magical Footwear", _RUNES["Magical Footwear"]["description"]
        )
        assert effects == {"flat_bonus_move_speed": 10.0}
        assert _RUNES["Magical Footwear"]["effects"] == {"flat_bonus_move_speed": 10.0}

    def test_the_rule_matches_only_the_two_runes_that_state_a_flat_grant(self):
        """A parser rule that fires elsewhere would rewrite unrelated runes.

        Relentless Hunter matches too and stays refused: its speed applies
        only out of combat, so the number is parsed and never compiled.
        """
        granting = {
            name
            for name, entry in _RUNES.items()
            if isinstance(entry, dict)
            and entry.get("description")
            and "flat_bonus_move_speed"
            in parse_rune_effects(name, entry["description"])[0]
        }
        assert granting == {"Magical Footwear", "Relentless Hunter"}

    def test_it_compiles_into_the_flat_movement_channel(self):
        effect = rune_effects.resolve_rune("Magical Footwear")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.MOVE_SPEED_FLAT

    def test_relentless_hunter_stays_refused_despite_its_parsed_number(self):
        """Out of combat is not this fight, so the parsed 8 buys nothing."""
        effect = rune_effects.resolve_rune("Relentless Hunter")
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert "out of combat" in effect.zero_policy.reason

    def _swiftmarch(self, **runes):
        request = {
            "champion": "Ahri",
            "level": 18,
            "role": "mid",
            "boots": "Swiftmarch",
            "role_quest_complete": True,
            "items": [],
            "enemies": [
                {"kind": "champion", "champion": "Darius", "level": 18, "role": "top"}
            ],
            "fight_duration": 10,
            "fight_mode": "time_based",
            "deterministic": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        }
        request.update(runes)
        return calculate_payload(request)

    def test_the_grant_moves_movement_speed_and_swiftmarch_damage(self):
        bare = self._swiftmarch(
            keystone="Grasp of the Undying", minor_runes=[], stat_shards=[]
        )
        held = self._swiftmarch(
            keystone="Grasp of the Undying",
            minor_runes=["Magical Footwear"],
            stat_shards=[],
        )
        assert held["champion_stats"]["move_speed"] - bare["champion_stats"][
            "move_speed"
        ] == pytest.approx(10.0, abs=0.1)
        assert held["total_damage"] - bare["total_damage"] == pytest.approx(
            3.6, abs=0.1
        )

    def test_without_swiftmarch_the_speed_moves_and_damage_does_not(self):
        """The control the old receipt lacked: no damage row reads the stat."""

        def fight(**overrides):
            request = {
                "champion": "Garen",
                "level": 18,
                "role": "top",
                "boots": "",
                "items": [],
                "enemies": [
                    {
                        "kind": "champion",
                        "champion": "Darius",
                        "level": 18,
                        "role": "top",
                    }
                ],
                "fight_duration": 10,
                "fight_mode": "time_based",
                "deterministic": True,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            }
            request.update(overrides)
            return calculate_payload(request)

        bare = fight(keystone="Grasp of the Undying", minor_runes=[], stat_shards=[])
        held = fight(
            keystone="Grasp of the Undying",
            minor_runes=["Magical Footwear"],
            stat_shards=[],
        )
        assert held["champion_stats"]["move_speed"] - bare["champion_stats"][
            "move_speed"
        ] == pytest.approx(10.0, abs=0.1)
        assert held["total_damage"] == pytest.approx(bare["total_damage"])

    def test_it_discloses_the_withheld_boots_half(self):
        disclosures = " ".join(
            rune_effects.resolve_rune("Magical Footwear").disclosures
        )
        assert "free boots" in disclosures
        assert "request's own to list" in disclosures
        assert "no damage row reads movement speed itself" in disclosures


class TestBiscuitDeliveryPricesTheHealthItKeeps:
    """The permanent half of a delivery rune: 30 maximum health per biscuit.

    Its refusal named two blockers. The cache carrying the sale price and
    not the health was one, and the parser closed it. The other was never a
    blocker but a question the request can answer, which is the shape every
    banked count on this page already takes.
    """

    def _fight(self, champion, consumed=None):
        payload = {
            "champion": champion,
            "level": 18,
            "role": "top",
            "items": [],
            "enemies": [
                {"kind": "champion", "champion": "Darius", "level": 18, "role": "top"}
            ],
            "fight_duration": 10,
            "fight_mode": "time_based",
            "deterministic": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "keystone": "Arcane Comet",
            "minor_runes": [],
            "stat_shards": [],
        }
        if consumed is not None:
            payload["minor_runes"] = ["Biscuit Delivery"]
            payload["rune_options"] = {
                "Biscuit Delivery": {"biscuits_consumed": consumed}
            }
        return calculate_payload(payload)

    def test_the_parser_reads_the_grant_and_the_number_of_biscuits(self):
        effects, _ = parse_rune_effects(
            "Biscuit Delivery", _RUNES["Biscuit Delivery"]["description"]
        )
        assert effects["max_health_per_consumable"] == 30.0
        assert effects["consumable_deliveries"] == 3

    def test_neither_rule_matches_another_rune(self):
        """Deep Ward's 1 health is a ward's, and says bonus rather than maximum."""
        matched = {
            key: sorted(
                name
                for name, entry in _RUNES.items()
                if isinstance(entry, dict)
                and entry.get("description")
                and key in parse_rune_effects(name, entry["description"])[0]
            )
            for key in ("max_health_per_consumable", "consumable_deliveries")
        }
        assert matched == {
            "max_health_per_consumable": ["Biscuit Delivery"],
            "consumable_deliveries": ["Biscuit Delivery"],
        }

    def test_it_grants_its_step_per_biscuit_and_stops_at_the_deliveries(self):
        effect = rune_effects.resolve_rune("Biscuit Delivery")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.BONUS_HEALTH
        assert effect.amount(_biscuits(0)) == 0.0
        assert effect.amount(_biscuits(2)) == pytest.approx(60.0)
        assert effect.amount(_biscuits(3)) == pytest.approx(90.0)
        assert effect.amount(_biscuits(9)) == pytest.approx(90.0)

    def test_the_count_is_an_option_bounded_by_the_deliveries_the_cache_names(self):
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        option = catalog["Biscuit Delivery"]["options"][0]
        assert option["key"] == "biscuits_consumed"
        assert (option["default"], option["maximum"]) == (0.0, 3.0)

    def test_three_biscuits_are_ninety_maximum_health_in_the_fight(self):
        bare = self._fight("Garen")
        fed = self._fight("Garen", 3)
        assert fed["champion_stats"]["health"] - bare["champion_stats"][
            "health"
        ] == pytest.approx(90.0)
        assert fed["champion_stats"]["bonus_health"] == pytest.approx(90.0)

    def test_a_kit_that_reads_maximum_health_prices_it_and_one_that_does_not_does_not(
        self,
    ):
        """The control and the case, one probe each.

        Garen's rotation reads no health of his own, so his total holds
        still while the stat moves; Cho'Gath's reads maximum health, so his
        moves with it.
        """
        assert self._fight("Garen", 3)["total_damage"] == pytest.approx(
            self._fight("Garen")["total_damage"]
        )
        bare = self._fight("Cho'Gath")
        fed = self._fight("Cho'Gath", 3)
        assert fed["champion_stats"]["health"] - bare["champion_stats"][
            "health"
        ] == pytest.approx(90.0)
        assert fed["total_damage"] - bare["total_damage"] == pytest.approx(9.0, abs=0.1)

    def test_it_discloses_the_default_and_the_withheld_restore(self):
        disclosures = " ".join(
            rune_effects.resolve_rune("Biscuit Delivery").disclosures
        )
        assert "whether the biscuit is drunk or sold" in disclosures
        assert "carries no clock" in disclosures


class TestCosmicInsightPricesItsItemHaste:
    """The haste half of a split rune: summoner spells stay outside the model.

    Its old receipt named the channel exactly — "no channel carries item
    haste" — and named what the channel would reach: the empowered-auto
    stream, which walks Titanic Crescent's declared cooldown and counts one
    proc per window. The closed stat set has the member now and the parser
    reads both numbers, so the item half lands where the stream reads it and
    the summoner half stays withheld the Ionian-Insight way.
    """

    def _fight(self, duration, runes, items):
        request = {
            "champion": "Garen",
            "level": 18,
            "role": "top",
            "items": items,
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
            "keystone": "Grasp of the Undying",
            "minor_runes": runes,
            "stat_shards": [],
        }
        return calculate_payload(request, deterministic=True)

    def test_the_parser_reads_both_hastes_into_the_cached_effects(self):
        effects, _ = parse_rune_effects(
            "Cosmic Insight", _RUNES["Cosmic Insight"]["description"]
        )
        assert effects == {"summoner_spell_haste": 18.0, "item_haste": 10.0}
        assert _RUNES["Cosmic Insight"]["effects"] == {
            "summoner_spell_haste": 18.0,
            "item_haste": 10.0,
        }

    def test_neither_rule_matches_another_rune(self):
        """Both hastes are section-anchored spellings only this rune writes."""
        matched = {
            key: sorted(
                name
                for name, entry in _RUNES.items()
                if isinstance(entry, dict)
                and entry.get("description")
                and key in parse_rune_effects(name, entry["description"])[0]
            )
            for key in ("summoner_spell_haste", "item_haste")
        }
        assert matched == {
            "summoner_spell_haste": ["Cosmic Insight"],
            "item_haste": ["Cosmic Insight"],
        }

    def test_it_compiles_into_the_item_haste_channel(self):
        effect = rune_effects.resolve_rune("Cosmic Insight")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.ITEM_HASTE
        context = rune_effects.RuneStatContext(
            level=18,
            is_melee=True,
            options={},
        )
        assert effect.amount(context) == pytest.approx(10.0)

    def test_the_haste_buys_a_crescent_proc_in_two_windows(self):
        """Ten haste shortens ten seconds to nine and a window holding the
        extra proc prices it. The row's own movement IS the total's: nothing
        else in the fight reads the channel, so any other mover would show
        here as a gap between the two deltas."""
        for duration, bare_count, held_count in ((20, 2, 3), (30, 3, 4)):
            bare = self._fight(duration, [], ["Titanic Hydra", "Dagger"])
            held = self._fight(
                duration, ["Cosmic Insight"], ["Titanic Hydra", "Dagger"]
            )
            assert held["champion_stats"]["item_haste"] == pytest.approx(10.0)
            assert bare["breakdown"]["active_Titanic Hydra"]["count"] == bare_count
            assert held["breakdown"]["active_Titanic Hydra"]["count"] == held_count
            row_delta = (
                held["breakdown"]["active_Titanic Hydra"]["total_damage"]
                - bare["breakdown"]["active_Titanic Hydra"]["total_damage"]
            )
            assert row_delta == pytest.approx(45.8, abs=0.2)
            # All four numbers are published to 0.1, so the two deltas may
            # part by two rounding steps.
            assert held["total_damage"] - bare["total_damage"] == pytest.approx(
                row_delta, abs=0.2
            )

    def test_on_a_coarse_swing_grid_the_haste_buys_nothing(self):
        """The honest boundary: the shortened window reopens inside a 19.5s
        fight, but Garen's next swing lands past its end, so the count holds
        at two and the rune prices nothing. Haste buys procs a window holds,
        not procs in the abstract."""
        bare = self._fight(19.5, [], ["Titanic Hydra"])
        held = self._fight(19.5, ["Cosmic Insight"], ["Titanic Hydra"])
        assert held["champion_stats"]["item_haste"] == pytest.approx(10.0)
        assert held["breakdown"]["active_Titanic Hydra"]["count"] == 2
        assert held["total_damage"] == pytest.approx(bare["total_damage"])

    def test_without_the_stream_the_stat_moves_and_damage_does_not(self):
        """The control the old receipt lacked: no damage row reads item
        haste itself, only the stream it shortens."""
        bare = self._fight(20, [], [])
        held = self._fight(20, ["Cosmic Insight"], [])
        assert held["champion_stats"]["item_haste"] == pytest.approx(10.0)
        assert held["total_damage"] == pytest.approx(bare["total_damage"])

    def test_it_discloses_the_withheld_summoner_half(self):
        disclosures = " ".join(rune_effects.resolve_rune("Cosmic Insight").disclosures)
        assert "10 item haste" in disclosures
        assert "18 summoner-spell haste is withheld" in disclosures
        assert "casts none" in disclosures


class TestJackOfAllTrades:
    """One of the path's priced runes: two channels off the build's own stat count."""

    def test_it_declares_both_channels_and_computes_them_from_one_count(self):
        """1 ability haste per stack; 8 adaptive at 5 stacks, 20 at 10."""
        effect = rune_effects.resolve_rune("Jack Of All Trades")
        assert isinstance(effect, rune_effects.RuneMultiStatGrantEffect)
        assert effect.stats == (
            rune_effects.RuneStat.ABILITY_HASTE,
            rune_effects.RuneStat.ADAPTIVE_FORCE,
        )
        haste = rune_effects.RuneStat.ABILITY_HASTE
        force = rune_effects.RuneStat.ADAPTIVE_FORCE
        assert effect.declared_amounts(_stat_context(4)) == {haste: 4.0, force: 0.0}
        assert effect.declared_amounts(_stat_context(5)) == {haste: 5.0, force: 8.0}
        assert effect.declared_amounts(_stat_context(10)) == {haste: 10.0, force: 20.0}

    def test_the_stacks_are_the_build_s_own_stat_types(self):
        """Counted off the item stat totals, and two engine keys for one
        game stat count once — a build wearing boots earns one stack for
        movement speed rather than two."""
        assert item_stat_type_count({}) == 0
        assert item_stat_type_count({"attack_damage": 40.0, "health": 300.0}) == 2
        assert (
            item_stat_type_count({"move_speed_flat": 45.0, "move_speed_percent": 5.0})
            == 1
        )
        assert item_stat_type_count({"attack_damage": 0.0}) == 0

    def test_the_cache_carries_the_step_and_both_gates(self):
        """Every number the compiler reads, checked against the cache.

        The three adaptive figures parse without conflict: the gates are
        claimed as gates and the total certifies them instead of
        conflicting with them.
        """
        jack = rune_effects.RUNE_EFFECTS["Jack Of All Trades"]
        assert jack["effects"] == {
            "ability_haste_per_stack": 1.0,
            "adaptive_force_stack_gates": [[5, 8.0], [10, 12.0]],
        }
        assert "parse_warnings" not in jack
        biscuit = rune_effects.RUNE_EFFECTS["Biscuit Delivery"]
        assert biscuit["effects"] == {
            "flat_gold": 5.0,
            "max_health_per_consumable": 30.0,
            "consumable_deliveries": 3,
        }


class TestInspirationOverTheWholePipeline:
    def test_a_refused_inspiration_rune_publishes_its_receipt_and_moves_nothing(
        self,
    ):
        bare = calculate_payload(_request())
        with_rune = calculate_payload(_request(minor_runes=["Triple Tonic"]))
        assert any("Triple Tonic is not priced" in note for note in with_rune["notes"])
        assert with_rune["champion_stats"] == bare["champion_stats"]
        assert with_rune["total_damage"] == pytest.approx(bare["total_damage"])

    def test_a_full_inspiration_secondary_pair_is_legal_and_prices_only_cosmic(
        self,
    ):
        """Two rows of one path is what a secondary path may hold. Cosmic
        books its stat into the card and, with no empowered-auto stream in
        this build, moves no total; Cash Back still refuses with its receipt."""
        bare = calculate_payload(_request())
        paired = calculate_payload(
            _request(minor_runes=["Cash Back", "Cosmic Insight"])
        )
        assert paired["champion_stats"]["item_haste"] == pytest.approx(10.0)
        assert paired["total_damage"] == pytest.approx(bare["total_damage"])
        assert not any(
            "Cosmic Insight is not priced" in note for note in paired["notes"]
        )
        assert any("Cash Back deals no damage" in note for note in paired["notes"])


class TestInspirationCoverage:
    def test_every_inspiration_minor_compiles(self):
        catalog = [
            entry
            for entry in rune_effects.rune_catalog()
            if entry["path"] == "Inspiration" and entry["row"]
        ]
        assert len(catalog) == 9
        assert all(entry["implemented"] is True for entry in catalog)
        assert {entry["name"] for entry in catalog} == set(DISPOSITIONS) | {
            "Jack Of All Trades",
            "Approach Velocity",
            "Magical Footwear",
            "Biscuit Delivery",
            "Cosmic Insight",
        }

    def test_only_the_two_gated_grants_declare_an_option(self):
        """A refusal reads no number, so it needs none asked for.

        The two exceptions are alike in the shape of what they wait on: the
        number is sourced and reaches the fight, and the state it is
        conditional on is the request's to state — where the holder stands,
        how many biscuits have been drunk. Magical Footwear's and Cosmic
        Insight's grants are unconditional, so they need none either.
        """
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        assert all(catalog[name]["options"] == [] for name in DISPOSITIONS)
        assert catalog["Jack Of All Trades"]["options"] == []
        assert catalog["Magical Footwear"]["options"] == []
        assert catalog["Cosmic Insight"]["options"] == []
        (option,) = catalog["Approach Velocity"]["options"]
        assert option["key"] == "near_impaired_enemy"
        assert option["kind"] == "switch"
        assert option["default"] == 0.0
        (biscuits,) = catalog["Biscuit Delivery"]["options"]
        assert biscuits["key"] == "biscuits_consumed"
        assert biscuits["kind"] == "count"
        assert biscuits["default"] == 0.0


def _stat_context(item_stat_types):
    """A stat context at level 18 carrying a count of item stat types."""
    return rune_effects.RuneStatContext(
        level=18,
        is_melee=False,
        options={},
        item_stat_types=item_stat_types,
    )
