"""Tests for the Ezreal champion module.

Hand-validated against the wiki (see /add-champion spec):
- Q rank 5, 100 total AD, 0 AP: 120 + 130% x 100 = 250 physical
- W rank 5, 50 bonus AD, 100 AP: 300 + 100% x 50 + 90% x 100 = 440 magic
- E rank 5, 0 AD, 0 AP: 280 magic
- R rank 3, 100 bonus AD, 200 AP: 750 + 100 + 110% x 200 = 1070 magic
- Q refund at 0 haste, rank 5: Q period = 4.5 - 1.5 = 3.0s;
  rate factor = 1.5; E rank 5 effective CD = 14 / 1.5 = 9.33s
"""

import pytest

from src.calculator import item_effects
from src.calculator.interpreters import on_hit_strike
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name


def _parse(
    ezreal_data,
    level,
    *,
    ap=0.0,
    ad=100.0,
    bonus_ad=0.0,
    haste=0.0,
    options=None,
    ranks=None,
):
    """Parse with a hand-crafted stats context for exact wiki math."""
    stats = {
        "attack_damage": ad,
        "base_attack_damage": ad - bonus_ad,
        "bonus_attack_damage": bonus_ad,
        "ability_power": ap,
        "ability_haste": haste,
        "critical_strike_chance": 0.0,
        "level": level,
    }
    return parse_champion_abilities(
        ezreal_data,
        level,
        ap,
        ability_ranks=ranks,
        champion_stats=stats,
        champion_options=options,
        target_stats={"target_max_health": 2000.0},
    )


_ALL_MAX = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(stats, abilities, items=None, **overrides):
    """Deterministic one-rotation burst against a 0/0 resist target."""
    config = {
        "target_health": 10000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 4.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, items or [], FightConfig(**config))


def _declared_per_hits(*owners: str, level: int = 18):
    """The on-hit strikes a build declares, through their own rules."""
    return on_hit_strike.per_hit_effects(
        owners,
        level=level,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )


def _per_hit_raw(item, stats, target_health, current_health=None):
    """One item on-hit application's raw damage, from the item source
    of truth (the same compiled spec the fight engine reads)."""
    effects = _declared_per_hits(
        str(item.get("name", "")), level=int(stats.get("level", 18))
    )
    assert effects, "expected an on-hit item"
    inputs = item_effects.DamageInputs(
        champion_stats=stats,
        level=int(stats.get("level", 18)),
        is_melee=True,
        target_max_health=target_health,
        target_current_health=(
            target_health if current_health is None else current_health
        ),
    )
    return sum(effect.source.raw_damage(inputs) for effect in effects)


class TestPassiveRisingSpellForce:
    """P: stat-buff only — 10% bonus attack speed per stack, no damage."""

    def test_default_full_stacks(self, ezreal_data) -> None:
        """Default 5 stacks grant 50% bonus attack speed, zero damage."""
        passive = _parse(ezreal_data, 9)["passive"]
        assert passive["stat_buff"]["bonus_attack_speed"] == pytest.approx(50.0)
        assert passive["total_raw"] == 0.0
        assert "+50% bonus attack speed" in passive["detail"]

    def test_partial_stacks(self, ezreal_data) -> None:
        """3 stacks grant 30% bonus attack speed."""
        passive = _parse(ezreal_data, 9, options={"passive_stacks": 3})["passive"]
        assert passive["stat_buff"]["bonus_attack_speed"] == pytest.approx(30.0)

    def test_zero_stacks_entry_still_emitted(self, ezreal_data) -> None:
        """Stat-buff slots never silently vanish (engine contract)."""
        passive = _parse(ezreal_data, 9, options={"passive_stacks": 0})["passive"]
        assert passive["stat_buff"]["bonus_attack_speed"] == 0.0
        assert passive["total_raw"] == 0.0

    def test_stacks_clamped_to_cap(self, ezreal_data) -> None:
        """Out-of-range option values clamp to the 5-stack cap."""
        passive = _parse(ezreal_data, 9, options={"passive_stacks": 12})["passive"]
        assert passive["stat_buff"]["bonus_attack_speed"] == pytest.approx(50.0)

    def test_stat_buff_feeds_fight_attack_speed(
        self, ezreal_data, attacker_stats
    ) -> None:
        """The 50% bonus AS applies through the champion's AS ratio."""
        abilities = _parse(ezreal_data, 18, ranks=_ALL_MAX)
        stats = attacker_stats()  # attack_speed 1.0, ratio 0.625
        _fight(stats, abilities)
        assert stats["attack_speed"] == pytest.approx(1.0 + 0.625 * 0.5)


class TestQMysticShot:
    """Q: physical, 130% total AD + 40% AP, applies item on-hits, no crit."""

    def test_damage_rank5(self, ezreal_data) -> None:
        """Rank 5 at 100 total AD, 0 AP: 120 + 130 = 250 physical."""
        q = _parse(ezreal_data, 18, ranks=_ALL_MAX)["Q"]
        assert q["damage_type"] == "physical"
        assert q["total_raw"] == pytest.approx(250.0)

    def test_ap_ratio(self, ezreal_data) -> None:
        """100 AP adds 40 damage (40% AP ratio)."""
        q = _parse(ezreal_data, 18, ap=100.0, ranks=_ALL_MAX)["Q"]
        assert q["total_raw"] == pytest.approx(290.0)

    def test_cannot_crit(self, ezreal_data) -> None:
        q = _parse(ezreal_data, 18, ranks=_ALL_MAX)["Q"]
        assert q["parts"][0].crit_effectiveness == 0.0

    def test_applies_item_on_hits_full_effectiveness(self, ezreal_data) -> None:
        """One hit per cast at 100%, triggering on-hit AND on-attack."""
        q = _parse(ezreal_data, 18, ranks=_ALL_MAX)["Q"]
        assert q["applies_item_on_hits"] == {
            "effectiveness": 1.0,
            "hits": 1,
            "triggers": ("on_hit", "on_attack"),
        }

    def test_other_slots_do_not_apply_item_on_hits(self, ezreal_data) -> None:
        abilities = _parse(ezreal_data, 18, ranks=_ALL_MAX)
        for slot in ("W", "E", "R"):
            assert "applies_item_on_hits" not in abilities[slot]


class TestCooldownRefund:
    """Q hits refund 1.5s on all cooldowns (continuous-rate model)."""

    def test_q_cooldown_rank5(self, ezreal_data) -> None:
        """Q period = 4.5 - 1.5 = 3.0s at 0 haste."""
        q = _parse(ezreal_data, 18, ranks=_ALL_MAX)["Q"]
        assert q["cooldown"] == pytest.approx(3.0)

    def test_w_e_r_divided_by_rate_factor(self, ezreal_data) -> None:
        """Rate factor 1 + 1.5/3.0 = 1.5 divides W/E/R cooldowns."""
        abilities = _parse(ezreal_data, 18, ranks=_ALL_MAX)
        assert abilities["W"]["cooldown"] == pytest.approx(8.0 / 1.5)
        assert abilities["E"]["cooldown"] == pytest.approx(14.0 / 1.5)
        assert abilities["R"]["cooldown"] == pytest.approx(90.0 / 1.5)

    def test_q_rank1_rate_factor(self, ezreal_data) -> None:
        """Q rank 1: period 5.5 - 1.5 = 4.0s; factor 1.375 on E."""
        abilities = _parse(ezreal_data, 18, ranks={"Q": 1, "W": 0, "E": 5, "R": 0})
        assert abilities["Q"]["cooldown"] == pytest.approx(4.0)
        assert abilities["E"]["cooldown"] == pytest.approx(14.0 / 1.375)

    def test_refund_is_flat_after_haste(self, ezreal_data) -> None:
        """The 1.5s comes off the HASTED cooldown: at 100 AH, Q's hasted
        2.25s - 1.5s floors at the 1.0s minimum period, so the emitted
        pre-haste cooldown is 1.0 x 2 = 2.0 and the rate factor is 2.5."""
        abilities = _parse(ezreal_data, 18, haste=100.0, ranks=_ALL_MAX)
        assert abilities["Q"]["cooldown"] == pytest.approx(2.0)
        assert abilities["E"]["cooldown"] == pytest.approx(14.0 / 2.5)

    def test_no_refund_without_q(self, ezreal_data) -> None:
        """Unranked Q means no refund stream — E keeps its base cooldown."""
        abilities = _parse(ezreal_data, 18, ranks={"Q": 0, "W": 0, "E": 5, "R": 0})
        assert "Q" not in abilities
        assert abilities["E"]["cooldown"] == pytest.approx(14.0)


class TestWEssenceFlux:
    """W: mark detonation — 100% bonus AD + 90% AP, always detonated."""

    def test_damage_rank5(self, ezreal_data) -> None:
        """Rank 5 at 50 bonus AD, 100 AP: 300 + 50 + 90 = 440 magic."""
        w = _parse(ezreal_data, 18, ad=150.0, bonus_ad=50.0, ap=100.0, ranks=_ALL_MAX)[
            "W"
        ]
        assert w["damage_type"] == "magic"
        assert w["total_raw"] == pytest.approx(440.0)


class TestEArcaneShift:
    """E: 60% bonus AD + 75% AP magic single hit."""

    def test_damage_rank5_base(self, ezreal_data) -> None:
        """Rank 5 with no bonus AD/AP: flat 280 magic."""
        e = _parse(ezreal_data, 18, ranks=_ALL_MAX)["E"]
        assert e["damage_type"] == "magic"
        assert e["total_raw"] == pytest.approx(280.0)

    def test_scalings(self, ezreal_data) -> None:
        """50 bonus AD and 100 AP add 30 + 75."""
        e = _parse(ezreal_data, 18, ad=150.0, bonus_ad=50.0, ap=100.0, ranks=_ALL_MAX)[
            "E"
        ]
        assert e["total_raw"] == pytest.approx(280.0 + 30.0 + 75.0)


class TestRTrueshotBarrage:
    """R: champion damage reads "Magic Damage" — never "Modified Damage"."""

    def test_damage_rank3(self, ezreal_data) -> None:
        """Rank 3 at 100 bonus AD, 200 AP: 750 + 100 + 220 = 1070 magic."""
        r = _parse(ezreal_data, 18, ad=200.0, bonus_ad=100.0, ap=200.0, ranks=_ALL_MAX)[
            "R"
        ]
        assert r["damage_type"] == "magic"
        assert r["total_raw"] == pytest.approx(1070.0)

    def test_modified_damage_row_ignored(self, ezreal_data) -> None:
        """The JSON's "Modified Damage" (150/225/300, minions/non-epic
        monsters) must never contribute: with zero stats, R is exactly
        its champion base — not the minion value, not a sum of both."""
        for rank, champion_base in ((1, 350.0), (2, 550.0), (3, 750.0)):
            r = _parse(ezreal_data, 18, ranks={"Q": 0, "W": 0, "E": 0, "R": rank})["R"]
            assert r["total_raw"] == pytest.approx(champion_base)


class TestAbilityItemOnHits:
    """Q's on-hit application in the fight engine."""

    def test_nashors_applied_once_at_full_effectiveness(
        self, ezreal_data, attacker_stats
    ) -> None:
        """One rotation, no autos, 0 MR: Q's single application deals
        Nashor's full per-hit damage exactly once."""
        nashors = get_item_by_name("Nashor's Tooth")
        abilities = _parse(ezreal_data, 18, ranks={"Q": 5, "W": 0, "E": 0, "R": 0})
        stats = attacker_stats()
        result = _fight(stats, abilities, [nashors], target_health=100000.0)
        row = result["breakdown"]["on_hit_items_Q"]
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(
            _per_hit_raw(nashors, stats, 100000.0)
        )

    def test_muramana_not_double_counted(self, ezreal_data, attacker_stats) -> None:
        """Muramana procs through the per-cast Shock path only: Q's
        on-hit application must NOT add the on-hit component on top."""
        muramana = get_item_by_name("Muramana")
        abilities = _parse(ezreal_data, 18, ranks={"Q": 5, "W": 0, "E": 0, "R": 0})
        stats = attacker_stats()
        result = _fight(stats, abilities, [muramana])
        assert "muramana_ability" in result["breakdown"]
        assert "on_hit_items_Q" not in result["breakdown"]

    def test_q_consumes_spellblade_one_rotation_no_autos(
        self, ezreal_data, attacker_stats
    ) -> None:
        """Q consumes spellblade itself (wiki: the proc can be "applied
        by an ability that triggers on-hit effects"). One rotation, no
        autos: casts arm charges and Q's single on-hit application
        consumes exactly one Trinity Force proc at full damage."""
        trinity = get_item_by_name("Trinity Force")
        abilities = _parse(ezreal_data, 18, ranks=_ALL_MAX)
        stats = attacker_stats()
        result = _fight(stats, abilities, [trinity], target_health=100000.0)
        row = result["breakdown"]["spellblade_Trinity Force"]
        assert row["count"] == 1
        effect = item_effects.resolve_damage_effects([trinity]).spellblade
        inputs = item_effects.DamageInputs(
            champion_stats=stats,
            level=18,
            is_melee=True,
            target_max_health=100000.0,
            target_current_health=100000.0,
        )
        assert row["damage_per_hit"] == pytest.approx(effect.source.raw_damage(inputs))

    def test_q_procs_spellblade_in_timed_fight_without_autos(
        self, ezreal_data, attacker_stats
    ) -> None:
        """The reported case: timed fight with auto uptime 0 must show
        Trinity procs on Q hits — one per Q cast (Q's 3.0s period
        clears Sheen's internal cooldown)."""
        trinity = get_item_by_name("Trinity Force")
        abilities = _parse(ezreal_data, 18, ranks=_ALL_MAX)
        stats = attacker_stats()
        result = _fight(
            stats,
            abilities,
            [trinity],
            one_rotation=False,
            fight_duration_seconds=9.0,
            auto_attack_uptime=0.0,
            target_health=100000.0,
        )
        row = result["breakdown"]["spellblade_Trinity Force"]
        assert row["count"] == result["breakdown"]["Q"]["casts"]
        assert row["count"] >= 2

    def test_muramana_still_applies_on_real_autos(
        self, ezreal_data, attacker_stats
    ) -> None:
        """The suppression is scoped to ability-carried applications —
        basic attacks still deal Muramana's on-hit component."""
        muramana = get_item_by_name("Muramana")
        abilities = _parse(ezreal_data, 18, ranks={"Q": 5, "W": 0, "E": 0, "R": 0})
        stats = attacker_stats()
        no_autos = _fight(dict(stats), abilities, [muramana])
        with_autos = _fight(
            dict(stats),
            abilities,
            [muramana],
            auto_attack_uptime=1.0,
            one_rotation=False,
        )
        assert with_autos["breakdown"]["auto_attacks"]["count"] > 0
        # Q's application contributes zero on-hit Muramana damage; the
        # auto stream contributes one application per auto.
        no_autos_row = no_autos["breakdown"].get("on_hit_Muramana", {})
        assert no_autos_row.get("total_damage", 0.0) == 0.0
        with_autos_row = with_autos["breakdown"]["on_hit_Muramana"]
        assert with_autos_row["count"] == (
            with_autos["breakdown"]["auto_attacks"]["count"]
        )
        assert with_autos_row["total_damage"] > 0.0
