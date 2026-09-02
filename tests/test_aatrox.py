"""Tests for Aatrox champion ability parsing and damage calculation."""

import pytest

from src.calculator.champions import aatrox
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.stats import calculate_total_stats
from tests import cc_review


class TestQThreeCasts:
    """Tests for Q (The Darkin Blade) three-cast mechanic."""

    @pytest.mark.parametrize(
        ("variant", "attribute"),
        [
            (0, "First Cast Damage"),
            (1, "First Sweetspot Damage"),
            (2, "Second Cast Damage"),
            (3, "Second Sweetspot Damage"),
            (4, "Third Cast Damage"),
            (5, "Third Sweetspot Damage"),
            (6, "Maximum Non-Minion Non-Sweetspot Damage"),
            (7, "Maximum Non-Minion Sweetspot Damage"),
        ],
    )
    def test_q_variant_selects_the_matching_sourced_row(
        self, aatrox_data, parse_at, variant, attribute
    ) -> None:
        stats, abilities = parse_at(
            aatrox_data,
            9,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_options={"q_variant": variant},
        )
        q = abilities["Q"]
        expected = extract_named(
            aatrox_data["abilities"]["Q"][0],
            attribute,
            q["rank"],
            stats,
        )
        assert q["total_raw"] == pytest.approx(expected)
        assert q["detail"] == f"Q variant: {attribute}."

    def test_q_returns_physical_damage(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(
            aatrox_data,
            9,
            champion_options={"q_variant": 6},
        )
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_sweetspot_deals_more_damage(self, aatrox_data, parse_at) -> None:
        _, normal = parse_at(
            aatrox_data,
            9,
            champion_options={"q_variant": 6},
        )
        _, sweetspot = parse_at(
            aatrox_data,
            9,
            champion_options={"q_variant": 7},
        )
        assert sweetspot["Q"]["total_raw"] > normal["Q"]["total_raw"]

    def test_q_sweetspot_is_default(self, aatrox_data, parse_at) -> None:
        _, default = parse_at(aatrox_data, 9)
        _, sweetspot = parse_at(
            aatrox_data,
            9,
            champion_options={"q_variant": 7},
        )
        assert abs(default["Q"]["total_raw"] - sweetspot["Q"]["total_raw"]) < 0.1

    def test_q_has_cooldown(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_normal_damage_matches_json(self, aatrox_data, parse_at) -> None:
        """Verify Q rank 1 normal damage = sum of 3 casts at base AD."""
        stats, abilities = parse_at(
            aatrox_data,
            1,
            champion_options={"q_variant": 6},
        )
        q = abilities["Q"]
        ad = stats["attack_damage"]
        # First Cast: 10 + 60% AD
        # Second Cast: 12.5 + 75% AD
        # Third Cast: 15 + 90% AD
        expected = (10 + 0.60 * ad) + (12.5 + 0.75 * ad) + (15 + 0.90 * ad)
        assert abs(q["total_raw"] - expected) < 0.5

    def test_q_authors_one_part_per_strike_a_second_apart(
        self, aatrox_data, parse_at
    ) -> None:
        """The triad is three timed parts, not one aggregate."""
        stats, abilities = parse_at(
            aatrox_data,
            9,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_options={"q_variant": 6},
        )
        parts = abilities["Q"]["parts"]
        assert [part.time_offset for part in parts] == [0.0, 1.0, 2.0]
        q_ability = aatrox_data["abilities"]["Q"][0]
        for part, attribute in zip(
            parts,
            ["First Cast Damage", "Second Cast Damage", "Third Cast Damage"],
            strict=False,
        ):
            assert part.amount == pytest.approx(
                extract_named(q_ability, attribute, 5, stats)
            )

    @pytest.mark.parametrize(
        ("variant", "offset"),
        [(0, 0.0), (1, 0.0), (2, 1.0), (3, 1.0), (4, 2.0), (5, 2.0)],
    )
    def test_a_single_strike_variant_lands_at_its_own_ordinal(
        self, aatrox_data, parse_at, variant, offset
    ) -> None:
        """First/second/third strike land 0 / 1 / 2 seconds after the cast."""
        _, abilities = parse_at(
            aatrox_data,
            9,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_options={"q_variant": variant},
        )
        parts = abilities["Q"]["parts"]
        assert len(parts) == 1
        assert parts[0].time_offset == offset

    @pytest.mark.parametrize("variant", [6, 7])
    def test_an_aggregate_variant_is_priced_from_its_three_components(
        self, aatrox_data, parse_at, variant
    ) -> None:
        """The two "Maximum Non-Minion" rows are the triad's own sum, so they
        are emitted as the three timed strikes that make them up."""
        _, abilities = parse_at(
            aatrox_data,
            9,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_options={"q_variant": variant},
        )
        parts = abilities["Q"]["parts"]
        assert [part.time_offset for part in parts] == [0.0, 1.0, 2.0]

    def test_q_three_casts_sum(self, aatrox_data, parse_at) -> None:
        """Q total damage equals sum of all three individual casts.

        Uses level 5 (R not yet ranked) so no R buff distorts the
        comparison between manual extraction and parse_abilities.
        """
        q_ability = aatrox_data["abilities"]["Q"][0]
        stats = calculate_total_stats(aatrox_data, 5, [])
        rank = 3  # Q rank 3 at level 5
        stats_ctx = dict(stats)

        first = extract_named(q_ability, "First Cast Damage", rank, stats_ctx)
        second = extract_named(q_ability, "Second Cast Damage", rank, stats_ctx)
        third = extract_named(q_ability, "Third Cast Damage", rank, stats_ctx)

        _, abilities = parse_at(
            aatrox_data,
            5,
            champion_options={"q_variant": 6},
        )
        assert abs(abilities["Q"]["total_raw"] - (first + second + third)) < 0.5


class TestPassiveOnHit:
    """Tests for P (Deathbringer Stance) on-hit parsing."""

    def test_passive_returns_on_hit(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(
            aatrox_data,
            9,
            target_stats={"target_max_health": 2000.0},
        )
        assert "passive" in abilities
        assert "on_hit" in abilities["passive"]

    def test_passive_damage_type_is_magic(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(
            aatrox_data,
            9,
            target_stats={"target_max_health": 2000.0},
        )
        assert abilities["passive"]["on_hit"]["damage_type"] == "magic"

    def test_passive_scales_with_level(self, aatrox_data, parse_at) -> None:
        target = {"target_max_health": 2000.0}
        _, low = parse_at(aatrox_data, 1, target_stats=target)
        _, high = parse_at(aatrox_data, 18, target_stats=target)
        assert high["passive"]["on_hit"]["damage_per_hit"] > (
            low["passive"]["on_hit"]["damage_per_hit"]
        )

    def test_passive_level1_percent(self, aatrox_data, parse_at) -> None:
        """Level 1 passive should deal ~4% of target max health."""
        _, abilities = parse_at(
            aatrox_data,
            1,
            target_stats={"target_max_health": 2000.0},
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        # 4% of 2000 = 80
        assert abs(damage - 80.0) < 1.0

    def test_passive_level18_percent(self, aatrox_data, parse_at) -> None:
        """Level 18 passive should deal 10% of target max health."""
        _, abilities = parse_at(
            aatrox_data,
            18,
            target_stats={"target_max_health": 2000.0},
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        assert abs(damage - 200.0) < 1.0

    def test_passive_level20_percent(self, aatrox_data, parse_at) -> None:
        """Level 20 passive should deal ~10.71% of target max health."""
        _, abilities = parse_at(
            aatrox_data,
            20,
            target_stats={"target_max_health": 2000.0},
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        assert abs(damage - 214.2) < 1.0


class TestRWorldEnder:
    """Tests for R (World Ender) stat buff."""

    def test_r_deals_no_damage(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 11)
        assert abilities["R"]["total_raw"] == 0.0

    def test_r_has_stat_buff(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 11)
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["bonus_attack_damage"] > 0

    def test_r_buff_increases_q_damage(self, aatrox_data, parse_at) -> None:
        """Q damage should be higher when R is ranked (buff applied)."""
        _, no_r = parse_at(aatrox_data, 5)
        _, with_r = parse_at(aatrox_data, 11)
        assert with_r["Q"]["total_raw"] > no_r["Q"]["total_raw"]

    def test_r_bonus_ad_percent_rank1(self, aatrox_data) -> None:
        """R rank 1 grants 20% bonus AD (the stat_buff percent_of read)."""
        r_ability = aatrox_data["abilities"]["R"][0]
        bonus = extract_value(r_ability, "Bonus Attack Damage", 1) / 100.0
        assert abs(bonus - 0.20) < 0.01

    def test_r_bonus_ad_percent_rank3(self, aatrox_data) -> None:
        """R rank 3 grants 40% bonus AD."""
        r_ability = aatrox_data["abilities"]["R"][0]
        bonus = extract_value(r_ability, "Bonus Attack Damage", 3) / 100.0
        assert abs(bonus - 0.40) < 0.01


class TestRStatBuffInFightEngine:
    """Tests for R stat buff integration with the fight engine."""

    def test_stat_buff_applied_to_champion_stats(self, aatrox_data, parse_at) -> None:
        """The fight engine should apply R's bonus AD to champion stats."""
        stats, abilities = parse_at(
            aatrox_data,
            11,
            target_stats={"target_max_health": 2000.0},
        )
        original_ad = stats["attack_damage"]

        calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )
        assert stats["attack_damage"] > original_ad

    def test_r_zero_damage_in_breakdown(self, aatrox_data, parse_at) -> None:
        """R should appear in fight engine but contribute 0 damage."""
        stats, abilities = parse_at(
            aatrox_data,
            11,
            target_stats={"target_max_health": 2000.0},
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )
        r_entry = result["breakdown"].get("R", {})
        assert r_entry.get("total_damage", 0.0) == 0.0


class TestWInfernalChains:
    """Tests for W (Infernal Chains) damage parsing."""

    def test_w_returns_physical_damage(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 3)
        assert "W" in abilities
        assert abilities["W"]["damage_type"] == "physical"

    def test_w_has_cooldown(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 3)
        assert abilities["W"]["cooldown"] > 0

    def test_w_uses_total_damage_both_hits(self, aatrox_data, parse_at) -> None:
        """W should price Total Damage (initial + pull-back), not single hit."""
        stats, abilities = parse_at(aatrox_data, 3)
        w = abilities["W"]
        ad = stats["attack_damage"]
        # W rank 1 Total Damage: 60 + 80% AD (both hits combined)
        expected_total = 60 + 0.80 * ad
        single_hit = 30 + 0.40 * ad
        assert abs(w["total_raw"] - expected_total) < 0.5
        assert w["total_raw"] > single_hit * 1.5

    def test_w_hits_twice_a_cached_tether_apart(self, aatrox_data, parse_at) -> None:
        """The pull-back is the same hit again when the 1.5s tether expires."""
        stats, abilities = parse_at(aatrox_data, 3)
        (part,) = abilities["W"]["parts"]
        assert part.count == 2
        assert part.time_offset == 0.0
        assert part.hit_interval == 1.5
        ad = stats["attack_damage"]
        assert part.amount == pytest.approx(30 + 0.40 * ad, abs=0.5)

    def test_the_two_w_hits_sum_to_the_cached_total_at_every_rank(
        self, aatrox_data
    ) -> None:
        """ "Total Damage" is exactly twice "Physical Damage" — the identity
        that lets the split keep the total."""
        w_ability = aatrox_data["abilities"]["W"][0]
        stats = calculate_total_stats(aatrox_data, 18, [])
        for rank in range(1, 6):
            single = extract_named(w_ability, "Physical Damage", rank, dict(stats))
            total = extract_named(w_ability, "Total Damage", rank, dict(stats))
            assert single * 2 == pytest.approx(total)


class TestEUmbralDash:
    """E (Umbral Dash) carries no enemy-damage attribute (damageType: None,
    no leveling row on any effect) — it emits a sourced zero-damage row
    rather than staying silently absent."""

    def test_e_present_zero_damage(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 9)
        entry = abilities["E"]
        assert entry["name"] == "Umbral Dash"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]


class TestReviewedCrowdControl:
    """Aatrox declares nothing, and not for want of a cached cadence.

    Q knocks up only in the Sweetspot - this module's own option - and W
    applies two different kinds across its two hits, while ``MODULE_CC``
    carries one kind per slot: see the module comment above
    ``parse_abilities``.
    """

    def test_the_kit_declares_nothing(self):
        """The empty dict is the declaration: every module states its
        review at ``MODULE_CC``, and stating none of it there is different
        from never having asked."""
        assert aatrox.MODULE_CC == {}
        assert aatrox.parse_abilities.cc_kinds == {}

    def test_the_darkin_blades_knockup_is_the_sweetspot_branchs(self):
        text = cc_review.slot_text(cc_review.kit("Aatrox"), "Q")
        assert "enemies hit within a sweetspot of the area" in text
        assert "are also knocked up for 0.25 seconds" in text
        assert any(row["key"] == "q_variant" for row in aatrox.OPTIONS)

    def test_infernal_chains_two_hits_do_not_control_alike(self):
        text = cc_review.slot_text(cc_review.kit("Aatrox"), "W")
        assert "slowing them for 1.5 seconds" in text
        assert "pulled to the center of the area" in text

    def test_the_darkin_blade_states_its_own_cadence(self):
        """The module's strike interval is the cached sentence's number."""
        text = cc_review.slot_text(cc_review.kit("Aatrox"), "Q")
        assert "with a 1-second static cooldown between casts" in text
        assert aatrox._Q_STRIKE_INTERVAL_SECONDS == 1.0

    def test_infernal_chains_states_when_its_second_hit_lands(self):
        text = cc_review.slot_text(cc_review.kit("Aatrox"), "W")
        assert (
            "a tether is formed between the target and the ground beneath them "
            "for 1.5 seconds" in text
        )
        assert (
            "if the tether is not broken by the end of its duration, the target "
            "is dealt the same physical damage again and pulled to the center of "
            "the area" in text
        )

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Aatrox") == ["Q", "W"]
        coverage = cc_review.fimbulwinter_coverage("Aatrox")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


def test_e_is_modeled_through_the_821_5_umbral_dash_heal() -> None:
    """E's own row is a sourced zero; the heal rule is what prices the slot.

    A level-18 itemless timed fight with autos pays Umbral Dash 821.5 —
    the receipt behind E's ``modeled`` label.
    """
    from src.calculator.calculate import calculate_payload
    from src.calculator.champions import get_champion_module_contract

    contract = get_champion_module_contract("Aatrox")
    assert set(contract.coverage.values()) == {"modeled"}
    assert contract.coverage_channels["E"] == ("self_healing_rule",)

    payload = calculate_payload(
        {
            "champion": "Aatrox",
            "level": 18,
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
    )
    paid = sum(
        float(event["amount"])
        for event in payload["self_healing_events"]
        if event["source"] == "Umbral Dash"
    )
    assert paid == pytest.approx(821.5, abs=0.1)


class TestModuleCoverage:
    """Every slot is covered: E's emitted row is a sourced zero and the
    heal channel is what prices it, so no slot is left out_of_scope."""

    def test_all_five_slots_covered(self) -> None:
        from src.calculator.champions import get_champion_module_contract

        contract = get_champion_module_contract("Aatrox")
        assert contract.coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
        assert contract.slots["E"] is aatrox.SLOTS["E"]
