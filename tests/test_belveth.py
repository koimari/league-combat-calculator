"""Tests for the Bel'Veth champion module.

Hand-validated against revision-backed patch 26.15 wiki data:
- Q rank 5, 100 total AD: 20 + 105% AD = 125 per dash; x4 casts = 500
- W rank 5, 0 AP: 320
- E rank 3, 100 AD, 0 bonus AS, 50% missing: (26 + 52) / 2 = 39 x 6 = 234
- R rank 1 explosion, 0 AP, 2000 max HP at 50% missing: 150 + 200 = 350
- R passive per stack, rank 1, 50 bonus AD: 2 + 3% x 50 = 3.5
"""

import pytest

from src.calculator import item_effects
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name


def _parse(
    belveth_data,
    level,
    *,
    ap=0.0,
    ad=100.0,
    bonus_ad=0.0,
    bonus_as=0.0,
    options=None,
    ranks=None,
    target=None,
):
    """Parse with a hand-crafted stats context for exact wiki math."""
    stats = {
        "attack_damage": ad,
        "base_attack_damage": ad - bonus_ad,
        "bonus_attack_damage": bonus_ad,
        "ability_power": ap,
        "attack_speed": 0.67,
        "attack_speed_ratio": 0.67,
        "bonus_attack_speed": bonus_as,
        "critical_strike_chance": 0.0,
        "level": level,
    }
    return parse_champion_abilities(
        belveth_data,
        level,
        ap,
        ability_ranks=ranks,
        champion_stats=stats,
        champion_options=options,
        target_stats=target or {"target_max_health": 2000.0},
    )


_ALL_MAX = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(stats, abilities, items=None, **overrides):
    """Deterministic sustained fight against a 0/0 resist target."""
    config = {
        "target_health": 10000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 4.0,
        "auto_attack_uptime": 1.0,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, items or [], FightConfig(**config))


class TestPassiveDeathInLavender:
    """P: full basic attacks, full on-hits, and bonus attack speed."""

    def test_stat_buff_level_1(self, belveth_data) -> None:
        """Temp AS at level 1 is 20%, no Lavender stacks by default."""
        abilities = _parse(belveth_data, 1)
        assert abilities["passive"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            20.0
        )

    def test_stat_buff_level_18(self, belveth_data) -> None:
        """The refreshed temporary AS remains 20% at level 18."""
        abilities = _parse(belveth_data, 18)
        assert abilities["passive"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            20.0
        )

    def test_per_level_arrays_cover_level_20(self, belveth_data) -> None:
        """Temporary AS is flat; no permanent stacks means 20% at level 20."""
        at_20 = _parse(belveth_data, 20)["passive"]["stat_buff"]
        assert at_20["bonus_attack_speed"] == pytest.approx(20.0)

    def test_lavender_stacks_add_per_stack_as(self, belveth_data) -> None:
        """Level 1: 20% temp + 100 stacks x 0.1% = 30% bonus AS."""
        abilities = _parse(belveth_data, 1, options={"lavender_stacks": 100})
        assert abilities["passive"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            30.0
        )

    def test_auto_attack_override_separates_attack_and_on_hit(
        self, belveth_data
    ) -> None:
        """Patch 26.15 live: full attack damage and full on-hit riders (the
        75% reduction was removed before release)."""
        override = _parse(belveth_data, 1)["passive"]["auto_attack_override"]
        assert override["damage_ratio"] == pytest.approx(1.0)
        assert override["on_hit_effectiveness"] == pytest.approx(1.0)

    def test_no_attack_speed_growth(self, belveth_data) -> None:
        """Her 0 AS growth is data, not module logic — verify it holds."""
        assert belveth_data["stats"]["attackSpeed"]["perLevel"] == 0


class TestQVoidSurge:
    """Q: q_casts directional dashes, physical, can crit."""

    def test_q_is_physical(self, belveth_data) -> None:
        assert _parse(belveth_data, 5)["Q"]["damage_type"] == "physical"

    def test_q_rank5_100ad_four_casts(self, belveth_data) -> None:
        """Rank 5, 100 AD: 20 + 105 = 125 per dash, x4 default = 500."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        assert abilities["Q"]["total_raw"] == pytest.approx(500.0)
        part = abilities["Q"]["parts"][0]
        assert part.amount == pytest.approx(125.0)
        assert part.count == 4

    def test_q_casts_option_scales_count(self, belveth_data) -> None:
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX, options={"q_casts": 2})
        assert abilities["Q"]["total_raw"] == pytest.approx(250.0)
        assert abilities["Q"]["cast_instances"] == 2

    def test_q_can_crit(self, belveth_data) -> None:
        assert _parse(belveth_data, 5)["Q"]["parts"][0].crit_effectiveness == 1.0

    def test_q_per_direction_cooldown(self, belveth_data) -> None:
        """Wiki per-direction CD (16 -> 12), not the JSON's 1s lockout."""
        assert _parse(belveth_data, 1)["Q"]["cooldown"] == pytest.approx(16.0)
        assert _parse(belveth_data, 18, ranks=_ALL_MAX)["Q"][
            "cooldown"
        ] == pytest.approx(12.0)


class TestWAboveAndBelow:
    """W: plain magic damage read."""

    def test_w_is_magic(self, belveth_data) -> None:
        assert _parse(belveth_data, 5)["W"]["damage_type"] == "magic"

    def test_w_rank5_no_ap(self, belveth_data) -> None:
        """Rank 5, 0 AP: 320; W no longer scales with bonus AD."""
        abilities = _parse(belveth_data, 18, bonus_ad=50.0, ranks=_ALL_MAX)
        assert abilities["W"]["total_raw"] == pytest.approx(320.0)

    def test_w_cooldown(self, belveth_data) -> None:
        assert _parse(belveth_data, 18, ranks=_ALL_MAX)["W"][
            "cooldown"
        ] == pytest.approx(8.0)


class TestERoyalMaelstrom:
    """E: slash count from bonus AS; damage interpolates by missing HP."""

    def test_e_is_physical(self, belveth_data) -> None:
        assert _parse(belveth_data, 5)["E"]["damage_type"] == "physical"

    def test_e_rank3_spec_sanity_check(self, belveth_data) -> None:
        """Rank 3, 100 AD, 50% missing: (26 + 52)/2 = 39 per slash.

        Passive temp AS is below the 40% threshold, so the count stays at
        the 6 base slashes: 234 total.
        """
        abilities = _parse(belveth_data, 10)  # E rank 3 by skill order
        assert abilities["E"]["rank"] == 3
        part = abilities["E"]["parts"][0]
        assert part.amount == pytest.approx(39.0)
        assert part.count == 6
        assert abilities["E"]["total_raw"] == pytest.approx(234.0)

    def test_e_interpolates_min_to_max(self, belveth_data) -> None:
        """0% missing reads the min attribute; 100% missing the max."""
        full = _parse(belveth_data, 10, options={"target_missing_hp_pct": 0})
        dead = _parse(belveth_data, 10, options={"target_missing_hp_pct": 100})
        assert full["E"]["parts"][0].amount == pytest.approx(26.0)  # 14 + 12% AD
        assert dead["E"]["parts"][0].amount == pytest.approx(52.0)  # 2x min

    def test_e_slash_count_scales_with_bonus_as(self, belveth_data) -> None:
        """floor(6 + bonus AS / 40): 100% items + 20% passive -> 9."""
        abilities = _parse(belveth_data, 1, bonus_as=100.0, ranks={"E": 1})
        assert abilities["E"]["parts"][0].count == 9

    def test_e_slash_count_includes_lavender_stacks(self, belveth_data) -> None:
        """Level 1 with 200 stacks: 20 + 20 = 40% bonus AS -> 7 slashes."""
        abilities = _parse(
            belveth_data, 1, options={"lavender_stacks": 200}, ranks={"E": 1}
        )
        assert abilities["E"]["parts"][0].count == 7

    def test_e_slash_count_ignores_true_form(self, belveth_data) -> None:
        """True Form's total-AS multiplier is not bonus AS."""
        off = _parse(belveth_data, 18, ranks=_ALL_MAX)
        on = _parse(belveth_data, 18, ranks=_ALL_MAX, options={"true_form": True})
        assert on["E"]["parts"][0].count == off["E"]["parts"][0].count

    def test_e_can_crit(self, belveth_data) -> None:
        assert _parse(belveth_data, 5)["E"]["parts"][0].crit_effectiveness == 1.0

    def test_e_cooldown(self, belveth_data) -> None:
        assert _parse(belveth_data, 10)["E"]["cooldown"] == pytest.approx(18.0)


class TestREndlessBanquet:
    """R active explosion, True Form buff, and the ramping on-hit."""

    def test_r_is_true_damage(self, belveth_data) -> None:
        assert _parse(belveth_data, 6)["R"]["damage_type"] == "true"

    def test_r_explosion_spec_sanity_check(self, belveth_data) -> None:
        """Rank 1, 0 AP, 2000 max HP at 50% missing: 150 + 200 = 350."""
        abilities = _parse(belveth_data, 6)
        assert abilities["R"]["total_raw"] == pytest.approx(350.0)

    def test_r_explosion_missing_health_component(self, belveth_data) -> None:
        """0% missing leaves only the flat + AP part."""
        abilities = _parse(
            belveth_data, 6, ap=100.0, options={"target_missing_hp_pct": 0}
        )
        assert abilities["R"]["total_raw"] == pytest.approx(300.0)  # 150 + 150% AP

    def test_true_form_off_by_default(self, belveth_data) -> None:
        """No stat_buff on R until the true_form option is enabled."""
        assert "stat_buff" not in _parse(belveth_data, 6)["R"]

    def test_true_form_stat_buff(self, belveth_data) -> None:
        """Rank 2, 50 bonus AD, 100 AP: 250 + 75 + 150 = 475 HP; +13% AS."""
        abilities = _parse(
            belveth_data,
            11,
            ap=100.0,
            bonus_ad=50.0,
            options={"true_form": True},
        )
        buff = abilities["R"]["stat_buff"]
        assert buff["health"] == pytest.approx(475.0)
        assert buff["total_attack_speed_percent"] == pytest.approx(13.0)

    def test_r_onhit_per_stack_value(self, belveth_data) -> None:
        """Rank 1, 50 bonus AD: 2 + 3% x 50 = 3.5 true damage per stack."""
        on_hit = _parse(belveth_data, 6, bonus_ad=50.0)["R_onhit"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(3.5)
        assert on_hit["damage_type"] == "true"
        assert on_hit["stacks_required"] == 1
        assert on_hit["ramping"] is True
        assert on_hit["applies_on_ability_on_hits"] is True

    def test_r_slots_absent_before_6(self, belveth_data) -> None:
        """Both R entries (active + on-hit) are rank-gated."""
        abilities = _parse(belveth_data, 5)
        assert "R" not in abilities
        assert "R_onhit" not in abilities


class TestFightEngineIntegration:
    """The passive's split modifier, ramping R procs, and True Form AS
    through the champion-agnostic fight engine."""

    def test_autos_deal_full_damage(self, belveth_data, attacker_stats) -> None:
        """Patch 26.15: vs 0 armor, per-hit auto damage is exactly AD."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        stats = attacker_stats(bonus_attack_speed=0.0)
        result = _fight(stats, abilities)
        auto = result["breakdown"]["auto_attacks"]
        assert auto["damage_per_hit"] == pytest.approx(100.0)

    def test_crit_autos_deal_full_damage(self, belveth_data, attacker_stats) -> None:
        """Patch 26.15: 100% crit is AD x 2.0, without the old 75% cut."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        stats = attacker_stats(bonus_attack_speed=0.0, critical_strike_chance=100.0)
        result = _fight(stats, abilities)
        auto = result["breakdown"]["auto_attacks"]
        assert auto["damage_per_hit"] == pytest.approx(100.0 * 2.0)

    def test_on_hit_items_reduced_to_75_percent(
        self, belveth_data, attacker_stats
    ) -> None:
        """Nashor's on-hit per-hit damage is 100% of its normal value."""
        nashors = get_item_by_name("Nashor's Tooth")
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        no_override = {k: v for k, v in abilities.items() if k != "passive"}
        stats = attacker_stats(bonus_attack_speed=0.0)

        def nashors_row(result):
            for entry in result["breakdown"].values():
                if "Nashor" in entry.get("name", ""):
                    return entry
            raise AssertionError("Nashor's on-hit row missing from breakdown")

        with_passive = nashors_row(_fight(dict(stats), abilities, [nashors]))
        without = nashors_row(_fight(dict(stats), no_override, [nashors]))
        assert with_passive["damage_per_hit"] == pytest.approx(
            1.0 * without["damage_per_hit"]
        )

    def test_r_onhit_ramps_with_auto_count(self, belveth_data, attacker_stats) -> None:
        """Hit k deals k x per-stack x 1.0 (on-hit modifier)."""
        abilities = _parse(
            belveth_data,
            18,
            bonus_ad=50.0,
            ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
        )
        per_stack = abilities["R_onhit"]["on_hit"]["damage_per_hit"]
        stats = attacker_stats(bonus_attack_speed=0.0)
        result = _fight(stats, abilities)

        autos = result["breakdown"]["auto_attacks"]["count"]
        procs = autos
        assert procs > 0
        expected = per_stack * 1.0 * procs * (procs + 1) / 2.0
        row = result["breakdown"]["on_hit_ability_R_onhit"]
        assert row["count"] == procs
        assert row["total_damage"] == pytest.approx(expected)

    def test_r_onhit_ramps_through_q_and_e_in_carrier_order(
        self, belveth_data, attacker_stats
    ) -> None:
        """No ambient autos: Q's four 100% applications lead E's six 18%
        applications on one shared R-passive stack sequence."""
        abilities = _parse(
            belveth_data,
            18,
            bonus_ad=50.0,
            ranks={"Q": 5, "W": 0, "E": 5, "R": 1},
        )
        per_stack = abilities["R_onhit"]["on_hit"]["damage_per_hit"]
        e_hits = abilities["E"]["applies_item_on_hits"]["hits"]
        assert e_hits == 6
        result = _fight(
            attacker_stats(bonus_attack_speed=0.0),
            abilities,
            auto_attack_uptime=0.0,
            one_rotation=True,
        )
        effectiveness = [1.0] * 4 + [0.18] * e_hits
        expected = per_stack * sum(
            stack * modifier for stack, modifier in enumerate(effectiveness, start=1)
        )
        row = result["breakdown"]["on_hit_ability_R_onhit"]
        assert row["count"] == len(effectiveness)
        assert row["total_damage"] == pytest.approx(expected)

    def test_passive_as_buff_raises_auto_count(
        self, belveth_data, attacker_stats
    ) -> None:
        """The stat_buff's 20% bonus AS feeds the fight's attack speed."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        stats = attacker_stats(bonus_attack_speed=0.0)
        _fight(stats, abilities)
        # attacker fixture: 1.0 base AS + 0.625 ratio x 20% = 1.125
        assert stats["attack_speed"] == pytest.approx(1.125)

    def test_true_form_multiplies_total_attack_speed(
        self, belveth_data, attacker_stats
    ) -> None:
        """R rank 3 True Form: final AS x1.20, applied AFTER bonus AS,
        and the champion stats panel reflects health + attack speed."""
        on = _parse(belveth_data, 18, ranks=_ALL_MAX, options={"true_form": True})
        off = _parse(belveth_data, 18, ranks=_ALL_MAX)
        stats_on = attacker_stats(bonus_attack_speed=0.0)
        stats_off = attacker_stats(bonus_attack_speed=0.0)
        _fight(stats_on, on)
        _fight(stats_off, off)
        assert stats_on["attack_speed"] == pytest.approx(
            1.20 * stats_off["attack_speed"]
        )
        assert stats_on["health"] > stats_off["health"]

    def test_passive_entry_adds_no_damage_row(
        self, belveth_data, attacker_stats
    ) -> None:
        """The stat/modifier passive never becomes a damage row."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        result = _fight(attacker_stats(bonus_attack_speed=0.0), abilities)
        assert "passive" not in result["breakdown"]


def _per_hit_raw(item, stats, target_health, current_health=None):
    """One item on-hit application's raw damage, from the item source
    of truth (the same compiled spec the fight engine reads)."""
    effects = item_effects.resolve_damage_effects([item])
    assert effects.per_hits, "expected an on-hit item"
    inputs = item_effects.DamageInputs(
        champion_stats=stats,
        level=int(stats.get("level", 18)),
        is_melee=True,
        target_max_health=target_health,
        target_current_health=(
            target_health if current_health is None else current_health
        ),
    )
    return sum(effect.source.raw_damage(inputs) for effect in effects.per_hits)


class TestAbilityItemOnHits:
    """Q and E apply item on-hit effects (100% and 12-24% respectively)."""

    def test_q_declares_on_hit_application(self, belveth_data) -> None:
        """Q: one application per dash at 100%, following q_casts."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        spec = abilities["Q"]["applies_item_on_hits"]
        assert spec["effectiveness"] == pytest.approx(1.0)
        assert spec["hits"] == 4
        two = _parse(belveth_data, 18, ranks=_ALL_MAX, options={"q_casts": 2})
        assert two["Q"]["applies_item_on_hits"]["hits"] == 2

    def test_e_declares_on_hit_application(self, belveth_data) -> None:
        """E: one application per slash at 12-24% by missing health."""
        mid = _parse(belveth_data, 18, ranks=_ALL_MAX)
        spec = mid["E"]["applies_item_on_hits"]
        assert spec["effectiveness"] == pytest.approx(0.18)  # 50% missing
        assert spec["hits"] == mid["E"]["parts"][0].count
        full = _parse(
            belveth_data, 18, ranks=_ALL_MAX, options={"target_missing_hp_pct": 0}
        )
        dead = _parse(
            belveth_data, 18, ranks=_ALL_MAX, options={"target_missing_hp_pct": 100}
        )
        assert full["E"]["applies_item_on_hits"]["effectiveness"] == pytest.approx(0.12)
        assert dead["E"]["applies_item_on_hits"]["effectiveness"] == pytest.approx(0.24)

    def test_w_and_r_do_not_apply_item_on_hits(self, belveth_data) -> None:
        """Only Q and E carry the on-hit application capability."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        assert "applies_item_on_hits" not in abilities["W"]
        assert "applies_item_on_hits" not in abilities["R"]

    def test_nashors_on_q_and_e_exact_values(
        self, belveth_data, attacker_stats
    ) -> None:
        """One rotation, NO autos, vs 0 MR: the only Nashor's damage is
        Q's 4 applications at 100% and E's 6 slashes at 18%."""
        nashors = get_item_by_name("Nashor's Tooth")
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        stats = attacker_stats(bonus_attack_speed=0.0)
        result = _fight(
            stats,
            abilities,
            [nashors],
            auto_attack_uptime=0.0,
            one_rotation=True,
            target_health=100000.0,
        )
        raw = _per_hit_raw(nashors, stats, 100000.0)
        slashes = abilities["E"]["parts"][0].count  # 6 (20% passive AS)
        q_row = result["breakdown"]["on_hit_items_Q"]
        e_row = result["breakdown"]["on_hit_items_E"]
        assert q_row["count"] == 4
        assert q_row["total_damage"] == pytest.approx(raw * 1.0 * 4)
        assert e_row["count"] == slashes
        assert e_row["total_damage"] == pytest.approx(raw * 0.18 * slashes)
        # No autos -> no auto-carried Nashor's row.
        assert result["breakdown"]["auto_attacks"]["count"] == 0

    def test_bork_on_q_decays_current_health(
        self, belveth_data, attacker_stats
    ) -> None:
        """BoRK applications read the rotation's modeled target HP:
        Q's own damage lands first, then each application decays it."""
        bork = get_item_by_name("Blade of the Ruined King")
        # Only Q ranked — isolates the application sequence.
        abilities = _parse(belveth_data, 18, ranks={"Q": 5, "W": 0, "E": 0, "R": 0})
        stats = attacker_stats(bonus_attack_speed=0.0)
        target_health = 2000.0
        result = _fight(
            dict(stats),
            abilities,
            [bork],
            auto_attack_uptime=0.0,
            one_rotation=True,
            target_health=target_health,
            target_armor=0.0,
        )
        # Mirror: 4 dashes' own damage (0 armor, no crit), then 4
        # applications at 100%, each reducing the modeled HP.
        q_total = result["breakdown"]["Q"]["total_damage"]
        hp = target_health - q_total
        expected = 0.0
        for _ in range(4):
            dmg = _per_hit_raw(bork, stats, target_health, hp) * 1.0
            expected += dmg
            hp -= dmg
        row = result["breakdown"]["on_hit_items_Q"]
        assert row["count"] == 4
        assert row["total_damage"] == pytest.approx(expected)

    def test_q_effectiveness_independent_of_passive(
        self, belveth_data, attacker_stats
    ) -> None:
        """Q on-hit is its own modifier, independent of the passive
        auto-only modifier; Q application damage must not change."""

        nashors = get_item_by_name("Nashor's Tooth")
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        no_passive = {k: v for k, v in abilities.items() if k != "passive"}
        stats = attacker_stats(bonus_attack_speed=0.0)
        kwargs = {
            "auto_attack_uptime": 0.0,
            "one_rotation": True,
            "target_health": 100000.0,
        }
        with_p = _fight(dict(stats), abilities, [nashors], **kwargs)
        without_p = _fight(dict(stats), no_passive, [nashors], **kwargs)
        assert with_p["breakdown"]["on_hit_items_Q"]["total_damage"] == pytest.approx(
            without_p["breakdown"]["on_hit_items_Q"]["total_damage"]
        )

    def test_energized_and_spellblade_not_triggered_by_abilities(
        self, belveth_data, attacker_stats
    ) -> None:
        """Energized (Statikk) is on-ATTACK: with no autos, Q/E on-hit
        applications never consume it."""
        shiv = get_item_by_name("Statikk Shiv")
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        result = _fight(
            attacker_stats(bonus_attack_speed=0.0),
            abilities,
            [shiv],
            auto_attack_uptime=0.0,
            one_rotation=True,
        )
        assert not any(
            "Statikk" in v.get("name", "") for v in result["breakdown"].values()
        )


def _kraken_raw_full_hp(kraken, stats, target_health):
    """Kraken's per-proc raw damage at full target HP, from the item
    source of truth (the compiled stacking spec)."""
    effects = item_effects.resolve_damage_effects([kraken])
    assert effects.stacking_on_hits, "expected a stacking on-hit item"
    inputs = item_effects.DamageInputs(
        champion_stats=stats,
        level=int(stats.get("level", 18)),
        is_melee=True,
        target_max_health=target_health,
        target_current_health=target_health,
    )
    return effects.stacking_on_hits[0].source.raw_damage(inputs)


class TestSharedOnHitCounter:
    """Kraken-style counters run on ONE shared hit sequence: rotation
    ability applications (cast order) first, then the fight's autos.
    The hit that lands the Nth stack fires the proc at ITS effectiveness.

    Huge target HP keeps Kraken's missing-HP bonus ~0 so expected
    values reduce to raw x effectiveness."""

    _HUGE_HP = 1_000_000.0

    def test_q_application_lands_third_stack_at_75(
        self, belveth_data, attacker_stats
    ) -> None:
        """Only Q ranked, no autos: 4 applications -> 1 proc, on a Q hit
        at Q's 100% effectiveness."""
        kraken = get_item_by_name("Kraken Slayer")
        abilities = _parse(belveth_data, 18, ranks={"Q": 5, "W": 0, "E": 0, "R": 0})
        stats = attacker_stats(bonus_attack_speed=0.0)
        result = _fight(
            dict(stats),
            abilities,
            [kraken],
            auto_attack_uptime=0.0,
            one_rotation=True,
            target_health=self._HUGE_HP,
        )
        raw = _kraken_raw_full_hp(kraken, stats, self._HUGE_HP)
        row = result["breakdown"]["on_hit_Kraken Slayer"]
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(raw * 1.0, rel=1e-3)

    def test_e_slashes_land_stacks_at_interpolated_effectiveness(
        self, belveth_data, attacker_stats
    ) -> None:
        """Only E ranked, no autos: 6 slashes -> 2 procs, both on E hits
        at the interpolated 18% (default 50% missing)."""
        kraken = get_item_by_name("Kraken Slayer")
        # Level 10: passive temp AS 20% < 40% -> exactly 6 slashes.
        abilities = _parse(belveth_data, 10, ranks={"Q": 0, "W": 0, "E": 3, "R": 0})
        assert abilities["E"]["parts"][0].count == 6
        stats = attacker_stats(bonus_attack_speed=0.0, level=10)
        result = _fight(
            dict(stats),
            abilities,
            [kraken],
            auto_attack_uptime=0.0,
            one_rotation=True,
            target_health=self._HUGE_HP,
        )
        raw = _kraken_raw_full_hp(kraken, stats, self._HUGE_HP)
        row = result["breakdown"]["on_hit_Kraken Slayer"]
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(raw * 0.18 * 2, rel=1e-3)

    def test_counter_carries_from_abilities_into_autos(
        self, belveth_data, attacker_stats
    ) -> None:
        """Q's 4 applications leave 1 leftover stack; the 2nd auto lands
        the next proc. Passive removed so the auto proc is at 100% —
        total = raw x (1.0 + 1.0). Separate per-source counters would
        give only the Q proc."""
        kraken = get_item_by_name("Kraken Slayer")
        abilities = _parse(belveth_data, 18, ranks={"Q": 5, "W": 0, "E": 0, "R": 0})
        no_passive = {k: v for k, v in abilities.items() if k != "passive"}
        stats = attacker_stats(bonus_attack_speed=0.0)  # 1.0 attacks/sec
        result = _fight(
            dict(stats),
            no_passive,
            [kraken],
            auto_attack_uptime=1.0,
            fight_duration_seconds=2.0,  # exactly 2 autos
            one_rotation=True,
            target_health=self._HUGE_HP,
        )
        assert result["breakdown"]["auto_attacks"]["count"] == 2
        raw = _kraken_raw_full_hp(kraken, stats, self._HUGE_HP)
        row = result["breakdown"]["on_hit_Kraken Slayer"]
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(raw * (1.0 + 1.0), rel=1e-3)

    def test_timed_mode_applications_scale_with_recasts(
        self, belveth_data, attacker_stats
    ) -> None:
        """Timed fights: applications = casts x per-cast hits."""
        nashors = get_item_by_name("Nashor's Tooth")
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        result = _fight(
            attacker_stats(bonus_attack_speed=0.0, ability_haste=100.0),
            abilities,
            [nashors],
            auto_attack_uptime=0.0,
            one_rotation=False,
            fight_duration_seconds=8.0,
            target_health=100000.0,
        )
        q_casts = result["breakdown"]["Q"]["casts"]
        assert q_casts > 1  # 12s CD halved by 100 haste recasts within 8s
        assert result["breakdown"]["on_hit_items_Q"]["count"] == q_casts * 4


class TestOnAttackTaxonomy:
    """On-hit vs on-attack trigger classification: Q applies on-hit only;
    E slashes are real attacks (wiki: 'on-hit, on-attack, and ability
    effects') and advance on-attack cadences like Guinsoo's phantom hit."""

    _HUGE_HP = 1_000_000.0

    def test_trigger_declarations(self, belveth_data) -> None:
        """Q carries on_hit only; E carries on_hit AND on_attack."""
        abilities = _parse(belveth_data, 18, ranks=_ALL_MAX)
        assert tuple(abilities["Q"]["applies_item_on_hits"]["triggers"]) == ("on_hit",)
        assert tuple(abilities["E"]["applies_item_on_hits"]["triggers"]) == (
            "on_hit",
            "on_attack",
        )

    def test_e_slashes_advance_phantom_counter(
        self, belveth_data, attacker_stats
    ) -> None:
        """E-only, no autos: the 6th slash fires Guinsoo's phantom hit,
        re-applying item on-hit damage at the slash's 18% effectiveness."""
        rageblade = get_item_by_name("Guinsoo's Rageblade")
        abilities = _parse(belveth_data, 18, ranks={"Q": 0, "W": 0, "E": 5, "R": 0})
        slashes = abilities["E"]["parts"][0].count  # 6 (passive 20% AS)
        assert slashes == 6
        stats = attacker_stats(bonus_attack_speed=0.0)
        result = _fight(
            dict(stats),
            abilities,
            [rageblade],
            auto_attack_uptime=0.0,
            one_rotation=True,
            target_health=self._HUGE_HP,
            target_magic_resistance=0.0,
        )
        raw = _per_hit_raw(rageblade, stats, self._HUGE_HP)  # 30 flat magic
        phantom_row = result["breakdown"]["on_hit_items_phantom"]
        assert phantom_row["count"] == 1  # phantom on the 6th slash only
        assert phantom_row["total_damage"] == pytest.approx(raw * 0.18)
        # The base slash applications are unchanged.
        e_row = result["breakdown"]["on_hit_items_E"]
        assert e_row["total_damage"] == pytest.approx(raw * 0.18 * slashes)

    def test_e_slashes_shift_auto_phantom_timeline(
        self, belveth_data, attacker_stats
    ) -> None:
        """Slashes and autos share ONE attack counter: 6 slashes fire one
        phantom, then 2 autos do not reach the next six-attack cadence."""
        rageblade = get_item_by_name("Guinsoo's Rageblade")
        abilities = _parse(belveth_data, 18, ranks={"Q": 0, "W": 0, "E": 5, "R": 0})
        no_passive = {k: v for k, v in abilities.items() if k != "passive"}
        stats = attacker_stats(bonus_attack_speed=0.0)  # 1.0 attacks/sec
        result = _fight(
            dict(stats),
            no_passive,
            [rageblade],
            auto_attack_uptime=1.0,
            fight_duration_seconds=2.0,  # exactly 2 autos
            one_rotation=True,
            target_health=self._HUGE_HP,
        )
        assert result["breakdown"]["auto_attacks"]["count"] == 2
        assert result["breakdown"]["on_hit_items_phantom"]["count"] == 1
        assert result["phantom_hit_autos"] == set()

    def test_q_applications_do_not_advance_phantom(
        self, belveth_data, attacker_stats
    ) -> None:
        """Q is on-hit only: with Q's 4 applications + 6 autos the first
        phantom still lands on auto #6 (index 5), exactly as without Q."""
        rageblade = get_item_by_name("Guinsoo's Rageblade")
        abilities = _parse(belveth_data, 18, ranks={"Q": 5, "W": 0, "E": 0, "R": 0})
        no_passive = {k: v for k, v in abilities.items() if k != "passive"}
        stats = attacker_stats(bonus_attack_speed=0.0)  # 1.0 attacks/sec
        result = _fight(
            dict(stats),
            no_passive,
            [rageblade],
            auto_attack_uptime=1.0,
            fight_duration_seconds=6.0,  # exactly 6 autos
            one_rotation=True,
            target_health=self._HUGE_HP,
        )
        assert result["breakdown"]["auto_attacks"]["count"] == 6
        assert result["phantom_hit_autos"] == {5}
        assert "on_hit_items_phantom" not in result["breakdown"]

    def test_phantom_on_slash_adds_on_hit_counter_stack(
        self, belveth_data, attacker_stats
    ) -> None:
        """A slash-fired phantom applies on-hit once more — one extra
        Kraken stack: 8 slashes + 1 phantom = 9 hits = 3 procs (vs 2
        without Rageblade), all at the slash's 18% effectiveness."""
        kraken = get_item_by_name("Kraken Slayer")
        rageblade = get_item_by_name("Guinsoo's Rageblade")
        abilities = _parse(
            belveth_data, 18, bonus_as=60.0, ranks={"Q": 0, "W": 0, "E": 5, "R": 0}
        )
        assert abilities["E"]["parts"][0].count == 8  # 20% passive + 60%
        stats = attacker_stats(bonus_attack_speed=60.0)
        kwargs = {
            "auto_attack_uptime": 0.0,
            "one_rotation": True,
            "target_health": self._HUGE_HP,
        }
        with_rageblade = _fight(dict(stats), abilities, [kraken, rageblade], **kwargs)
        without = _fight(dict(stats), abilities, [kraken], **kwargs)
        raw = _kraken_raw_full_hp(kraken, stats, self._HUGE_HP)
        row = with_rageblade["breakdown"]["on_hit_Kraken Slayer"]
        assert without["breakdown"]["on_hit_Kraken Slayer"]["count"] == 2
        assert row["count"] == 3
        assert row["total_damage"] == pytest.approx(raw * 0.18 * 3, rel=1e-3)


class TestStatsBonusAttackSpeed:
    """stats.py exposes total bonus AS% for AS-scaling champion mechanics."""

    def test_no_items_no_growth_is_zero(self, belveth_data, parse_at) -> None:
        """Bel'Veth has 0 AS growth: bonus AS is 0 at every level."""
        stats, _ = parse_at(belveth_data, 18)
        assert stats["bonus_attack_speed"] == pytest.approx(0.0)

    def test_item_as_feeds_e_slash_count(self, belveth_data, parse_at) -> None:
        """AS items raise the slash count through the real stats path."""
        nashors = get_item_by_name("Nashor's Tooth")
        _, bare = parse_at(belveth_data, 18)
        stats, with_item = parse_at(belveth_data, 18, items=[nashors])
        assert stats["bonus_attack_speed"] > 0.0
        assert with_item["E"]["parts"][0].count > bare["E"]["parts"][0].count
