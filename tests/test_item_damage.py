"""Per-item damage effects exercised through calculate_fight_damage.

One test class per item passive/active, asserting the item's damage
contribution inside a full fight (most use Ahri or a minimal stats dict as
the vehicle). Split from test_item_effects.py by altitude, not by item:
that file unit-tests the ITEM_EFFECTS accessor functions against a patched
registry; this one asserts fight-engine behavior with live parsed item data.
"""

import pytest

from src.calculator.champions.ahri import (
    parse_abilities as parse_ahri_abilities,
)
from src.calculator.damage import (
    calculate_fight_damage,
    _simulate_bork_damage,
    _calculate_phantom_hits,
    _calculate_kraken_procs,
    _calculate_hullbreaker_procs,
)


class TestBastionbreakerShapedCharge:
    """Tests for Bastionbreaker Shaped Charge passive."""

    @pytest.fixture
    def bastionbreaker(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Bastionbreaker")

    def test_shaped_charge_ranged_damage(self) -> None:
        """Ranged: 15 + 0.75 * 22 lethality = 31.5 true damage."""
        from src.calculator.item_effects import calculate_shaped_charge_damage

        stats = {"lethality": 22.0}
        damage = calculate_shaped_charge_damage(
            stats, is_melee=False, fight_duration=5.0
        )
        assert abs(damage - 31.5) < 0.01

    def test_shaped_charge_melee_damage(self) -> None:
        """Melee: 30 + 1.5 * 22 lethality = 63 true damage."""
        from src.calculator.item_effects import calculate_shaped_charge_damage

        stats = {"lethality": 22.0}
        damage = calculate_shaped_charge_damage(
            stats, is_melee=True, fight_duration=5.0
        )
        assert abs(damage - 63.0) < 0.01

    def test_shaped_charge_multiple_procs(self) -> None:
        """45s cooldown: 50s fight = 2 procs."""
        from src.calculator.item_effects import calculate_shaped_charge_damage

        stats = {"lethality": 22.0}
        damage = calculate_shaped_charge_damage(
            stats, is_melee=False, fight_duration=50.0
        )
        expected = 31.5 * 2
        assert abs(damage - expected) < 0.01

    def test_ahri_full_fight_with_bastionbreaker(
        self,
        ahri_data: dict,
        bastionbreaker: dict,
    ) -> None:
        """Ahri level 18 with only Bastionbreaker, one rotation.

        Shaped Charge should add ~32 true damage.
        """
        from src.calculator.stats import calculate_total_stats

        items = [bastionbreaker]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        sc = fight["breakdown"]["shaped_charge_Bastionbreaker"]
        assert (
            abs(sc["total_damage"] - 32) <= 1
        ), f"Shaped Charge {sc['total_damage']:.1f} expected ~32"


class TestRapidFirecannonSharpshooter:
    """Tests for Rapid Firecannon's Sharpshooter energized proc."""

    def test_parsed_values_match_expected(self) -> None:
        """Verify parser extracts 40 magic damage from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Rapid Firecannon", items)
        assert parsed is not None
        assert parsed["base"] == 40.0
        assert parsed["damage_type"] == "magic"

    def test_single_proc_magic_damage(self) -> None:
        """One energized proc: 40 magic damage mitigated by MR."""
        from src.calculator.damage import calculate_fight_damage
        from src.calculator.resistance import apply_resistance

        stats = {
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "critical_strike_chance": 0.0,
            "is_melee": False,
            "level": 18,
        }
        import random

        random.seed(0)
        fight = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=0,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Rapid Firecannon"}],
        )
        rfc = fight["breakdown"]["on_hit_once_Rapid Firecannon"]
        # 100 MR, no magic pen → effective MR = 100
        expected = apply_resistance(40.0, 100.0)
        assert abs(rfc["total_damage"] - expected) < 0.01
        assert rfc["damage_type"] == "magic"

    def test_no_proc_without_autos(self) -> None:
        """No auto attacks means no energized proc."""
        from src.calculator.damage import calculate_fight_damage

        stats = {
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "critical_strike_chance": 0.0,
            "is_melee": False,
            "level": 18,
        }
        fight = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=0,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Rapid Firecannon"}],
        )
        assert "on_hit_once_Rapid Firecannon" not in fight["breakdown"]


class TestOverlordBloodmailTyranny:
    """Tests for Overlord's Bloodmail Tyranny passive parser."""

    def test_parsed_ratio_matches_expected(self) -> None:
        """Verify parser extracts the 2.5% bonus health to AD ratio."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Overlord's Bloodmail", items)
        assert parsed is not None
        assert abs(parsed["bonus_health_to_ad_ratio"] - 0.025) < 0.001


class TestBloodlettersCurseVileDecay:
    """Tests for Bloodletter's Curse stacking MR reduction passive."""

    @pytest.fixture
    def bloodletters(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Bloodletter's Curse")

    def test_stacking_mr_reduction_helper(self) -> None:
        """get_stacking_mr_reduction returns effect when item is present."""
        from src.calculator.item_effects import get_stacking_mr_reduction

        items = [{"name": "Bloodletter's Curse"}]
        effect = get_stacking_mr_reduction(items)
        assert effect is not None
        assert effect["mr_reduction_per_stack"] == 0.075
        assert effect["max_stacks"] == 4

    def test_no_stacking_mr_reduction_without_item(self) -> None:
        """get_stacking_mr_reduction returns None without the item."""
        from src.calculator.item_effects import get_stacking_mr_reduction

        items = [{"name": "Liandry's Torment"}]
        assert get_stacking_mr_reduction(items) is None

    def test_effective_mr_decreases_per_ability(
        self,
        ahri_data: dict,
        bloodletters: dict,
    ) -> None:
        """Final effective MR should be lower than base when stacks apply."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodletters]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        # 4 stacks = 30% MR reduction: 100 * 0.70 = 70 effective MR
        assert fight["effective_mr"] == pytest.approx(70.0, abs=0.1)

    def test_ahri_level18_total_damage_within_tolerance(
        self,
        ahri_data: dict,
        bloodletters: dict,
    ) -> None:
        """Ahri level 18 with Bloodletter's Curse, one rotation.

        Target: 1000 HP, 100 MR, 100 Armor.
        Expected ~919 total damage (within ±5%).
        """
        from src.calculator.stats import calculate_total_stats

        items = [bloodletters]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        expected = 919
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_damage_higher_than_without_passive(
        self,
        ahri_data: dict,
        bloodletters: dict,
    ) -> None:
        """Damage with Bloodletter's Curse should exceed damage without MR reduction."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodletters]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_with = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        # Without item: no MR reduction passive
        fight_without = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=[],
            one_rotation=True,
        )
        assert fight_with["total_damage"] > fight_without["total_damage"]

    def test_no_effect_on_physical_only_damage(self) -> None:
        """Stacking MR reduction should not affect physical-only abilities."""
        # Craft a minimal physical-only scenario
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "attack_speed": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Physical",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        items_with = [{"name": "Bloodletter's Curse"}]

        fight_with = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=1.0,
            items=items_with,
            one_rotation=True,
        )
        fight_without = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=1.0,
            items=[],
            one_rotation=True,
        )
        assert fight_with["breakdown"]["Q"]["total_damage"] == pytest.approx(
            fight_without["breakdown"]["Q"]["total_damage"], abs=0.01
        )


class TestShadowflameCinderbloom:
    """Tests for Shadowflame Cinderbloom passive (magic/true crit below 40% HP)."""

    @pytest.fixture
    def shadowflame(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Shadowflame")

    def test_shadowflame_item_effect_registered(self) -> None:
        """Shadowflame should be registered in ITEM_EFFECTS."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Shadowflame")
        assert effect is not None
        assert effect["type"] == "magic_true_crit"
        assert effect["crit_multiplier"] == 1.20
        assert effect["health_threshold"] == 0.40

    def test_no_bonus_when_target_above_threshold(self) -> None:
        """No Shadowflame bonus when all damage is dealt above 40% HP."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            "Q": {
                "name": "Test",
                "casts": 1,
                "total_damage": 100.0,
                "damage_type": "magic",
            },
        }
        ability_damages = {
            "Q": {"damage_type": "magic", "magic_damage": 100, "total_raw": 100},
        }
        # Target at 1000 HP, threshold 400 — 100 damage won't cross it
        bonus = _calculate_shadowflame_bonus(breakdown, ability_damages, 1000.0)
        assert bonus == 0.0

    def test_bonus_when_target_below_threshold(self) -> None:
        """Damage dealt when target is below 40% should get 20% bonus."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        # Q does 700 damage (drops target from 1000 to 300, below 400)
        # W does 200 magic damage (target already below 40%)
        breakdown = {
            "Q": {
                "name": "Big Nuke",
                "casts": 1,
                "total_damage": 700.0,
                "damage_type": "magic",
            },
            "W": {
                "name": "Follow Up",
                "casts": 1,
                "total_damage": 200.0,
                "damage_type": "magic",
            },
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 0.0,
                "damage_type": "physical",
            },
        }
        ability_damages = {
            "Q": {"damage_type": "magic", "magic_damage": 700, "total_raw": 700},
            "W": {"damage_type": "magic", "magic_damage": 200, "total_raw": 200},
        }
        bonus = _calculate_shadowflame_bonus(breakdown, ability_damages, 1000.0)
        # W (200) dealt below threshold, gets 20% bonus = 40
        assert abs(bonus - 40.0) < 0.01

    def test_physical_damage_not_affected(self) -> None:
        """Physical damage below threshold should not get Shadowflame bonus."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            "Q": {
                "name": "Nuke",
                "casts": 1,
                "total_damage": 700.0,
                "damage_type": "magic",
            },
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 200.0,
                "damage_type": "physical",
            },
        }
        ability_damages = {
            "Q": {"damage_type": "magic", "magic_damage": 700, "total_raw": 700},
        }
        bonus = _calculate_shadowflame_bonus(breakdown, ability_damages, 1000.0)
        # Auto attacks are physical — no crit bonus
        assert bonus == 0.0

    def test_mixed_damage_splits_correctly(self) -> None:
        """Mixed abilities (like Ahri Q) should split into magic and true events."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        # Q: 300 magic (mitigated) + 500 true = 800 total
        # Target at 1000 HP: after Q magic (300), HP = 700 (above 400)
        # After Q true (500), HP = 200 (Q true hit at 700, above 400)
        # W: 150 magic at HP 200 (below 400) → bonus = 150 * 0.2 = 30
        breakdown = {
            "Q": {
                "name": "Orb",
                "casts": 1,
                "total_damage": 800.0,
                "damage_type": "mixed",
            },
            "W": {
                "name": "Fire",
                "casts": 1,
                "total_damage": 150.0,
                "damage_type": "magic",
            },
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 0.0,
                "damage_type": "physical",
            },
        }
        ability_damages = {
            "Q": {
                "damage_type": "mixed",
                "magic_damage": 500,
                "true_damage": 500,
                "total_raw": 1000,
            },
            "W": {"damage_type": "magic", "magic_damage": 150, "total_raw": 150},
        }
        bonus = _calculate_shadowflame_bonus(breakdown, ability_damages, 1000.0)
        assert abs(bonus - 30.0) < 0.01

    def test_damage_higher_with_shadowflame(
        self,
        ahri_data: dict,
        shadowflame: dict,
    ) -> None:
        """Ahri's total damage should increase with Shadowflame passive."""
        from src.calculator.stats import calculate_total_stats

        items = [shadowflame]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_with = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        fight_without = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=[],
            one_rotation=True,
        )
        assert fight_with["total_damage"] > fight_without["total_damage"]
        assert "shadowflame_Shadowflame" in fight_with["breakdown"]

    def test_ahri_full_build_within_tolerance(self, ahri_data: dict) -> None:
        """Ahri level 18, 6 items vs 1000 HP / 100 Armor / 100 MR.

        Items: Rabadon's, Liandry's, Bloodletter's Curse, Malignance,
               Shadowflame, Blackfire Torch.
        Expected AP: 717, expected total damage ~3700 (within 5%).
        """
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.stats import calculate_total_stats

        items = [
            get_item_by_name("Rabadon's Deathcap"),
            get_item_by_name("Liandry's Torment"),
            get_item_by_name("Bloodletter's Curse"),
            get_item_by_name("Malignance"),
            get_item_by_name("Shadowflame"),
            get_item_by_name("Blackfire Torch"),
        ]
        stats = calculate_total_stats(ahri_data, 18, items)
        assert stats["ability_power"] == 717

        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        expected = 3700
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_synthetic_recast_row_counted_once(self) -> None:
        """A synthetic recast row (e.g. Ambessa Q2) is one damage event, not two.

        Q (400) and Q2 (400) drop the target from 1000 to 200; W (300 magic)
        then lands below the 400 threshold -> bonus = 300 * 0.2 = 60.
        Counting the Q2 breakdown row AGAIN as an "item effect" event would
        add a bogus below-threshold event worth another 80.
        """
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            "Q": {
                "name": "Cast",
                "casts": 1,
                "total_damage": 400.0,
                "damage_type": "magic",
            },
            "Q2": {
                "name": "Recast",
                "casts": 1,
                "total_damage": 400.0,
                "damage_type": "magic",
            },
            "W": {
                "name": "Follow Up",
                "casts": 1,
                "total_damage": 300.0,
                "damage_type": "magic",
            },
        }
        ability_damages = {
            "Q": {"damage_type": "magic", "magic_damage": 400, "total_raw": 400},
            "Q2": {
                "damage_type": "magic",
                "magic_damage": 400,
                "total_raw": 400,
                "recast_of": "Q",
            },
            "W": {"damage_type": "magic", "magic_damage": 300, "total_raw": 300},
        }
        # Default cast_order includes "Q2" — step 1 already consumes it.
        bonus = _calculate_shadowflame_bonus(breakdown, ability_damages, 1000.0)
        assert abs(bonus - 60.0) < 0.01

    def test_ambessa_q2_not_double_counted(
        self,
        ambessa_data: dict,
        shadowflame: dict,
        parse_at,
    ) -> None:
        """Ambessa (real synthetic Q2 row) + Shadowflame + Luden's Echo.

        Target health is chosen so that whether the 40% threshold is crossed
        before the fight's only magic event (the Luden's proc, last in event
        order) depends on Q2 being counted once vs twice.  A probe run
        against a huge target measures the per-row damages D (none scale
        with target health here); we then pick

            H = (sum of all rows before Luden's + D_Q2 / 2) / 0.6

        With every row counted once, HP at the Luden's proc is
        0.4*H + D_Q2/2 — above the threshold, so there is NO Cinderbloom
        bonus.  Double-counting Q2 pushes it below and fabricates one.
        """
        from src.calculator.data_fetcher import get_item_by_name

        items = [shadowflame, get_item_by_name("Luden's Echo")]
        stats, abilities = parse_at(ambessa_data, 18, items=items)

        def run(target_health: float) -> dict:
            return calculate_fight_damage(
                dict(stats),
                abilities,
                target_health=target_health,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                ability_haste=0.0,
                items=items,
                one_rotation=True,
            )

        probe = run(100000.0)["breakdown"]
        assert "Q2" in probe and probe["Q2"]["total_damage"] > 0
        assert "shadowflame_Shadowflame" not in probe  # nothing crosses 40%
        luden_key = "proc_Luden's Echo"
        luden_damage = probe[luden_key]["total_damage"]
        assert luden_damage > 0
        before_luden = sum(
            row["total_damage"] for key, row in probe.items() if key != luden_key
        )
        target_health = (before_luden + probe["Q2"]["total_damage"] / 2) / 0.6

        fight = run(target_health)
        # Guard: same per-row damages at the tuned target health.
        assert fight["breakdown"]["Q2"]["total_damage"] == pytest.approx(
            probe["Q2"]["total_damage"]
        )
        assert fight["breakdown"][luden_key]["total_damage"] == pytest.approx(
            luden_damage
        )
        # With Q2 counted once, the threshold is never crossed before the
        # only magic event — no Cinderbloom bonus row may exist.
        assert "shadowflame_Shadowflame" not in fight["breakdown"]


class TestActualizerAmpRow:
    """The informational Actualizer row must reflect only rows the amp touched.

    The ability amp is applied in exactly two places in the fight engine:
    rotation ability rows (cast_order keys, damage.py step 2) and
    ``is_ability_damage`` item procs (Stormsurge / Zaz'Zak's Realmspike,
    step 7).  The display-only ``ability_amp_*`` row's "amplified base"
    must mirror that exact set — not burns, on-hits, or other item rows.
    """

    @pytest.fixture
    def actualizer(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Actualizer")

    @staticmethod
    def _run(ahri_data: dict, items: list) -> dict:
        from src.calculator.stats import calculate_total_stats

        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        return calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
            include_actives=True,
        )

    @staticmethod
    def _amp_row_and_expected(fight: dict, extra_keys: tuple = ()) -> tuple:
        """Return (amp row, hand-computed bonus over the rows the amp touched)."""
        breakdown = fight["breakdown"]
        row = breakdown["ability_amp_Actualizer"]
        amp = row["multiplier"]
        amped_keys = ("Q", "Q2", "W", "E", "R") + extra_keys
        base = sum(
            breakdown[key]["total_damage"] for key in amped_keys if key in breakdown
        )
        # base already includes the amp: contribution = base * (amp-1) / amp.
        return row, base * (amp - 1.0) / amp

    def test_amp_row_excludes_burn_rows(
        self,
        ahri_data: dict,
        liandrys: dict,
        actualizer: dict,
    ) -> None:
        """Liandry's burn is not ability-amped; it must not inflate the row."""
        fight = self._run(ahri_data, [actualizer, liandrys])
        assert any(key.startswith("burn_") for key in fight["breakdown"])
        row, expected = self._amp_row_and_expected(fight)
        assert row["total_damage"] == pytest.approx(expected, abs=0.01)

    def test_amp_row_includes_ability_damage_procs(
        self,
        ahri_data: dict,
        actualizer: dict,
    ) -> None:
        """Stormsurge's proc IS ability-amped and belongs in the row's base."""
        from src.calculator.data_fetcher import get_item_by_name

        fight = self._run(ahri_data, [actualizer, get_item_by_name("Stormsurge")])
        assert "proc_Stormsurge" in fight["breakdown"]
        row, expected = self._amp_row_and_expected(fight, ("proc_Stormsurge",))
        assert row["total_damage"] == pytest.approx(expected, abs=0.01)


class TestBloodsongSpellbladeAndExposeWeakness:
    """Tests for Bloodsong's Spellblade and Expose Weakness passives."""

    @pytest.fixture
    def bloodsong(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Bloodsong")

    def test_bloodsong_registered_as_spellblade(self) -> None:
        """Bloodsong should be in ITEM_EFFECTS with type spellblade."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Bloodsong")
        assert effect is not None
        assert effect["type"] == "spellblade"
        assert effect["base_ad_ratio"] == 1.0
        assert effect["damage_type"] == "physical"

    def test_spellblade_damage_equals_base_ad(self) -> None:
        """Bloodsong spellblade should deal 100% base AD."""
        from src.calculator.item_effects import get_spellblade_damage

        stats = {"base_attack_damage": 104.0}
        damage = get_spellblade_damage("Bloodsong", stats)
        assert abs(damage - 104.0) < 0.01

    def test_two_procs_in_five_second_fight(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Bloodsong should proc twice in a 5-second fight (CD starts after attack)."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=items,
            one_rotation=False,
        )
        sb = fight["breakdown"]["spellblade_Bloodsong"]
        assert sb["procs"] == 2

    def test_expose_weakness_present_in_breakdown(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Expose Weakness bonus should appear in the fight breakdown."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=items,
            one_rotation=False,
        )
        assert "expose_weakness_Bloodsong" in fight["breakdown"]
        ew = fight["breakdown"]["expose_weakness_Bloodsong"]
        assert ew["total_damage"] > 0

    def test_expose_weakness_uses_ranged_rate_for_ahri(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Ahri is ranged; Expose Weakness should use the 5% rate."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=items,
            one_rotation=False,
        )
        ew = fight["breakdown"]["expose_weakness_Bloodsong"]
        assert ew["amplifier"] == pytest.approx(1.05, abs=0.001)

    def test_ahri_level18_bloodsong_total_damage(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Ahri level 18 with Bloodsong vs 1000 HP / 100 Armor / 100 MR.

        5-second fight, 100% auto uptime. Expected ~1161 total damage (±5%).
        """
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=items,
            one_rotation=False,
        )
        expected = 1161
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_no_expose_weakness_without_auto_attacks(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """No auto attacks means no spellblade procs, so no Expose Weakness."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        assert "expose_weakness_Bloodsong" not in fight["breakdown"]

    def test_expose_weakness_melee_uses_eight_percent(self) -> None:
        """Melee champions should use the 8% Expose Weakness rate."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=[{"name": "Bloodsong"}],
            one_rotation=False,
        )
        ew = fight["breakdown"]["expose_weakness_Bloodsong"]
        assert ew["amplifier"] == pytest.approx(1.08, abs=0.001)


class TestDuskAndDawnSpellbladeAndDoubleOnHit:
    """Tests for Dusk and Dawn's Spellblade and Double On-Hit passives."""

    @pytest.fixture
    def dusk_and_dawn(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Dusk and Dawn")

    @pytest.fixture
    def nashors(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Nashor's Tooth")

    def test_dusk_and_dawn_registered_as_spellblade(self) -> None:
        """Dusk and Dawn should be in ITEM_EFFECTS with type spellblade."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Dusk and Dawn")
        assert effect is not None
        assert effect["type"] == "spellblade"
        assert effect["damage_type"] == "magic"
        assert effect["base_ad_ratio"] == 0.75
        assert effect["ap_ratio"] == 0.10
        assert effect["double_on_hit"] is True

    def test_spellblade_damage_formula(self) -> None:
        """Dusk and Dawn spellblade should deal 75% base AD + 10% AP."""
        from src.calculator.item_effects import get_spellblade_damage

        stats = {"base_attack_damage": 104.0, "ability_power": 160.0}
        damage = get_spellblade_damage("Dusk and Dawn", stats)
        expected = 0.75 * 104.0 + 0.10 * 160.0  # 78 + 16 = 94
        assert abs(damage - expected) < 0.01

    def test_two_procs_in_four_second_fight(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
        nashors: dict,
    ) -> None:
        """Dusk and Dawn should proc twice in a 4-second fight."""
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn, nashors]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=4.0,
            auto_attack_uptime=1.0,
            ability_haste=stats.get("ability_haste", 0.0),
            items=items,
            one_rotation=False,
        )
        sb = fight["breakdown"]["spellblade_Dusk and Dawn"]
        assert sb["procs"] == 2

    def test_double_on_hit_present_in_breakdown(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
        nashors: dict,
    ) -> None:
        """Double on-hit bonus should appear in breakdown when Nashor's is present."""
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn, nashors]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=4.0,
            auto_attack_uptime=1.0,
            ability_haste=stats.get("ability_haste", 0.0),
            items=items,
            one_rotation=False,
        )
        assert "double_on_hit_Dusk and Dawn" in fight["breakdown"]
        doh = fight["breakdown"]["double_on_hit_Dusk and Dawn"]
        assert doh["procs"] == 2
        assert doh["total_damage"] > 0

    def test_no_double_on_hit_without_on_hit_items(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
    ) -> None:
        """No double on-hit entry when no on-hit items are present."""
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=4.0,
            auto_attack_uptime=1.0,
            ability_haste=stats.get("ability_haste", 0.0),
            items=items,
            one_rotation=False,
        )
        assert "double_on_hit_Dusk and Dawn" not in fight["breakdown"]

    def test_ahri_level18_dnd_nashors_total_damage(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
        nashors: dict,
    ) -> None:
        """Ahri level 18, D&D + Nashor's vs 1000 HP / 100 Armor / 100 MR.

        4-second fight, 100% auto uptime. Expected ~1656 total damage (+-5%).
        """
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn, nashors]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=4.0,
            auto_attack_uptime=1.0,
            ability_haste=stats.get("ability_haste", 0.0),
            items=items,
            one_rotation=False,
        )
        expected = 1656
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_double_on_hit_with_wits_end(self) -> None:
        """Double on-hit should also work with Wit's End."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "magic_damage": 200,
                "total_raw": 200,
                "damage_type": "magic",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=[{"name": "Dusk and Dawn"}, {"name": "Wit's End"}],
            one_rotation=False,
        )
        assert "double_on_hit_Dusk and Dawn" in fight["breakdown"]
        doh = fight["breakdown"]["double_on_hit_Dusk and Dawn"]
        assert doh["procs"] == 2
        assert doh["total_damage"] > 0

    def test_double_on_hit_with_bork(self) -> None:
        """Double on-hit should work with Blade of the Ruined King."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=[
                {"name": "Dusk and Dawn"},
                {"name": "Blade of the Ruined King"},
            ],
            one_rotation=False,
        )
        assert "double_on_hit_Dusk and Dawn" in fight["breakdown"]
        doh = fight["breakdown"]["double_on_hit_Dusk and Dawn"]
        assert doh["total_damage"] > 0

    def test_kraken_extra_hits_from_double_on_hit(self) -> None:
        """Double on-hit procs should count as extra hits for Kraken Slayer."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        # Only 2 auto attacks + 2 double on-hit procs = 4 effective hits
        # = 1 Kraken proc (every 3rd hit). Without double on-hit, 2 autos
        # wouldn't reach the 3-hit threshold.
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 3.0,
                "physical_damage": 200,
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=2.0,
            auto_attack_uptime=1.0,
            ability_haste=0.0,
            items=[
                {"name": "Dusk and Dawn"},
                {"name": "Kraken Slayer"},
            ],
            one_rotation=False,
        )
        # 2 autos + 2 double on-hit = 4 effective hits >= 3, so Kraken procs
        assert "on_hit_Kraken Slayer" in fight["breakdown"]


class TestEclipseEverRisingMoon:
    """Tests for Eclipse's Ever Rising Moon passive (% max HP physical proc)."""

    @pytest.fixture
    def eclipse(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Eclipse")

    def test_eclipse_registered_in_item_effects(self) -> None:
        """Eclipse should be registered in ITEM_EFFECTS with correct type."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Eclipse")
        assert effect is not None
        assert effect["type"] == "max_hp_proc"
        assert effect["damage_type"] == "physical"
        assert effect["target_max_hp_ratio_melee"] == 0.06
        assert effect["target_max_hp_ratio_ranged"] == 0.04
        assert effect["cooldown"] == 6.0

    def test_ranged_single_proc_damage(self) -> None:
        """Ranged: 4% of 2000 max HP = 80 raw physical damage (one proc)."""
        from src.calculator.item_effects import calculate_eclipse_damage

        damage = calculate_eclipse_damage(
            target_max_health=2000.0,
            is_melee=False,
            fight_duration=0.0,
        )
        assert abs(damage - 80.0) < 0.01

    def test_melee_single_proc_damage(self) -> None:
        """Melee: 6% of 2000 max HP = 120 raw physical damage (one proc)."""
        from src.calculator.item_effects import calculate_eclipse_damage

        damage = calculate_eclipse_damage(
            target_max_health=2000.0,
            is_melee=True,
            fight_duration=0.0,
        )
        assert abs(damage - 120.0) < 0.01

    def test_multiple_procs_over_duration(self) -> None:
        """6s cooldown: 12s fight = 3 procs (0s, 6s, 12s)."""
        from src.calculator.item_effects import calculate_eclipse_damage

        damage = calculate_eclipse_damage(
            target_max_health=1000.0,
            is_melee=False,
            fight_duration=12.0,
        )
        # 3 procs * 4% * 1000 = 120
        assert abs(damage - 120.0) < 0.01

    def test_zero_target_health_returns_zero(self) -> None:
        """Zero target max HP should result in zero Eclipse damage."""
        from src.calculator.item_effects import calculate_eclipse_damage

        damage = calculate_eclipse_damage(
            target_max_health=0.0,
            is_melee=True,
            fight_duration=5.0,
        )
        assert damage == 0.0

    def test_eclipse_appears_in_fight_breakdown(self) -> None:
        """Eclipse proc should appear in fight breakdown when item is present."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=[{"name": "Eclipse"}],
            one_rotation=True,
        )
        assert "proc_Eclipse" in fight["breakdown"]
        proc = fight["breakdown"]["proc_Eclipse"]
        assert proc["damage_type"] == "physical"
        assert proc["total_damage"] > 0

    def test_eclipse_damage_mitigated_by_armor(self) -> None:
        """Eclipse physical damage should be reduced by target armor."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        # 0 armor fight
        fight_no_armor = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=0,
            target_magic_resistance=100,
            fight_duration_seconds=1.0,
            items=[{"name": "Eclipse"}],
            one_rotation=True,
        )
        # 100 armor fight
        fight_with_armor = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=1.0,
            items=[{"name": "Eclipse"}],
            one_rotation=True,
        )
        eclipse_no_armor = fight_no_armor["breakdown"]["proc_Eclipse"]["total_damage"]
        eclipse_with_armor = fight_with_armor["breakdown"]["proc_Eclipse"][
            "total_damage"
        ]
        # 100 armor => 50% mitigation
        assert abs(eclipse_with_armor - eclipse_no_armor * 0.5) < 0.01

    def test_ahri_full_fight_with_eclipse(
        self,
        ahri_data: dict,
        eclipse: dict,
    ) -> None:
        """Ahri level 18 with Eclipse vs 2000 HP / 100 Armor / 100 MR.

        One rotation, no autos. Eclipse should add ~40 mitigated damage.
        (Ranged: 4% of 2000 = 80 raw, 50% mitigated by 100 armor = 40)
        """
        from src.calculator.stats import calculate_total_stats

        items = [eclipse]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        proc = fight["breakdown"]["proc_Eclipse"]
        assert proc["name"] == "Eclipse (Ever Rising Moon)"
        # Ranged 4% of 2000 = 80 raw. With armor pen from Eclipse lethality,
        # effective armor < 100, so mitigated damage > 40.
        assert proc["total_damage"] > 35
        assert proc["total_damage"] < 80  # Must be mitigated, less than raw

    def test_no_eclipse_when_item_not_present(self) -> None:
        """Eclipse proc should not appear when item is not equipped."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            items=[],
            one_rotation=True,
        )
        assert "proc_Eclipse" not in fight["breakdown"]


class TestExperimentalHexplate:
    """Tests for Experimental Hexplate Overdrive (50% bonus AS on R cast)."""

    def test_hexplate_registered_in_item_effects(self) -> None:
        """Hexplate should be registered in ITEM_EFFECTS."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Experimental Hexplate")
        assert effect is not None
        assert effect["type"] == "ult_attack_speed_buff"
        assert effect["bonus_attack_speed_percent"] == 50.0
        assert effect["duration"] == 8.0

    def test_hexplate_increases_auto_count(self) -> None:
        """Hexplate bonus AS (from stats) should yield more autos than without."""
        base_stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        # Hexplate 50% bonus AS is now baked into stats by calculate_total_stats
        buffed_stats = {**base_stats, "attack_speed": 1.3125}
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight_without = calculate_fight_damage(
            base_stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[],
            one_rotation=True,
        )
        fight_with = calculate_fight_damage(
            buffed_stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Experimental Hexplate"}],
            one_rotation=True,
        )
        autos_without = fight_without["breakdown"]["auto_attacks"]["count"]
        autos_with = fight_with["breakdown"]["auto_attacks"]["count"]
        assert autos_with > autos_without

    def test_hexplate_auto_count_5s_fight(self) -> None:
        """With buffed AS=1.3125 (from stats), 5s => 6 autos."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.3125,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Experimental Hexplate"}],
            one_rotation=True,
        )
        # AS already includes Hexplate 50% bonus from stats.py
        # floor(1.3125 * 5 * 1.0) = 6
        assert fight["breakdown"]["auto_attacks"]["count"] == 6

    def test_hexplate_full_fight_duration(self) -> None:
        """With buffed AS=1.3125 for full 15s fight: floor(1.3125 * 15) = 19."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.3125,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=15.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Experimental Hexplate"}],
            one_rotation=True,
        )
        # AS includes Hexplate bonus from stats.py, applied for full duration
        # floor(1.3125 * 15 * 1.0) = 19
        assert fight["breakdown"]["auto_attacks"]["count"] == 19

    def test_hexplate_note_in_result(self) -> None:
        """Fight result should include a note about R assumption."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.3125,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Experimental Hexplate"}],
            one_rotation=True,
        )
        assert len(fight["notes"]) == 1
        assert "Experimental Hexplate" in fight["notes"][0]
        assert "R is assumed" in fight["notes"][0]

    def test_no_note_without_hexplate(self) -> None:
        """No notes when Hexplate is not equipped."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[],
            one_rotation=True,
        )
        assert fight["notes"] == []


class TestFiendhunterBolts:
    """Tests for Fiendhunter Bolts (3 empowered autos after R cast)."""

    def test_fiendhunter_registered_in_item_effects(self) -> None:
        """Fiendhunter should be registered in ITEM_EFFECTS."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Fiendhunter Bolts")
        assert effect is not None
        assert effect["type"] == "ult_empowered_autos"
        assert effect["bonus_attack_speed_percent"] == 50.0
        assert effect["empowered_auto_count"] == 3
        assert effect["reduced_crit_ratio"] == 0.80
        assert effect["natural_crit_true_damage_ratio"] == 0.15

    def test_zero_crit_empowered_autos_deal_80pct_crit(self) -> None:
        """With 0% crit chance, empowered autos crit at 80% of crit multiplier.

        AD=100, crit_mult=2.0, 80% crit = 100 * 2.0 * 0.80 = 160 raw.
        No true damage (0% natural crit chance).
        """
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=0,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Fiendhunter Bolts"}],
            one_rotation=True,
        )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["empowered_count"] == 3
        # Empowered: 100 * 2.0 * 0.80 = 160 per hit (0 armor), 3 hits
        # Normal autos (0% crit): 100 per hit
        # Total empowered physical = 160 * 3 = 480
        empowered_phys = 160.0 * 3
        # buffed_as = 1.0 + 0.625 * 0.50 = 1.3125
        # 3 / (1.3125 * 1.0) = 2.2857s; remaining = 2.7143s
        # normal_autos = floor(1.0 * 2.7143) = 2
        normal_phys = 100.0 * 2
        assert abs(autos["total_damage"] - (empowered_phys + normal_phys)) < 1
        assert "fiendhunter_true_damage" not in fight["breakdown"]

    def test_100_crit_empowered_autos_deal_normal_crit_plus_true(self) -> None:
        """With 100% crit chance, empowered autos deal full crit + 15% true.

        AD=100, crit_mult=2.0, all natural crits.
        Physical: 100 * 2.0 = 200 per hit.
        True: 200 * 0.15 = 30 per hit.
        """
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 100,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=0,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Fiendhunter Bolts"}],
            one_rotation=True,
        )
        autos = fight["breakdown"]["auto_attacks"]
        # 3 empowered at full crit = 200 each, 2 normal crits = 200 each
        assert autos["num_crits"] == 5  # all autos crit at 100%
        fh_true = fight["breakdown"]["fiendhunter_true_damage"]
        # True damage: 200 * 0.15 = 30 per hit, 3 empowered hits = 90
        assert abs(fh_true["total_damage"] - 90.0) < 0.01

    def test_ahri_level_18_fiendhunter_zero_crits(self) -> None:
        """Ahri level 18 with Fiendhunter Bolts, 3 autos, 0 natural crits.

        AD=104, crit_mult=2.0, 25% crit chance but no crits rolled.
        Empowered: 104 * 2.0 * 0.80 = 166.4 raw, /2 = 83.2 mitigated.
        Total: 83.2 * 3 = 249.6 -> 250.
        """
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        # Force no crits: random.random() always returns 0.99 (> 0.25)
        with patch("src.calculator.damage.random.random", return_value=0.99):
            fight = calculate_fight_damage(
                stats,
                abilities,
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=3.0,
                auto_attack_uptime=1.0,
                items=[{"name": "Fiendhunter Bolts"}],
                one_rotation=True,
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["empowered_count"] == 3
        assert autos["count"] == 3
        assert autos["num_crits"] == 0
        assert round(autos["total_damage"]) == 250
        assert "fiendhunter_true_damage" not in fight["breakdown"]

    def test_ahri_level_18_fiendhunter_one_crit(self) -> None:
        """Ahri level 18, Fiendhunter, 3 autos, 1 natural crit -> 302."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        # 1st auto crits (0.1 < 0.25), 2nd and 3rd don't (0.99 > 0.25)
        crit_rolls = iter([0.1, 0.99, 0.99])
        with patch("src.calculator.damage.random.random", side_effect=crit_rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=3.0,
                auto_attack_uptime=1.0,
                items=[{"name": "Fiendhunter Bolts"}],
                one_rotation=True,
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 1
        assert (
            round(
                autos["total_damage"]
                + fight["breakdown"]["fiendhunter_true_damage"]["total_damage"]
            )
            == 302
        )

    def test_ahri_level_18_fiendhunter_two_crits(self) -> None:
        """Ahri level 18, Fiendhunter, 3 autos, 2 natural crits -> 354."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        crit_rolls = iter([0.1, 0.1, 0.99])
        with patch("src.calculator.damage.random.random", side_effect=crit_rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=3.0,
                auto_attack_uptime=1.0,
                items=[{"name": "Fiendhunter Bolts"}],
                one_rotation=True,
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 2
        total = (
            autos["total_damage"]
            + fight["breakdown"]["fiendhunter_true_damage"]["total_damage"]
        )
        assert round(total) == 354

    def test_ahri_level_18_fiendhunter_three_crits(self) -> None:
        """Ahri level 18, Fiendhunter, 3 autos, 3 natural crits -> 406."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        crit_rolls = iter([0.1, 0.1, 0.1])
        with patch("src.calculator.damage.random.random", side_effect=crit_rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=3.0,
                auto_attack_uptime=1.0,
                items=[{"name": "Fiendhunter Bolts"}],
                one_rotation=True,
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 3
        total = (
            autos["total_damage"]
            + fight["breakdown"]["fiendhunter_true_damage"]["total_damage"]
        )
        assert round(total) == 406

    def test_correct_total_auto_count(self) -> None:
        """3 empowered autos + remaining normal autos at base AS."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Fiendhunter Bolts"}],
            one_rotation=True,
        )
        autos = fight["breakdown"]["auto_attacks"]
        # buffed_as = 1.0 + 0.625 * 0.50 = 1.3125
        # 3 empowered autos take 3 / (1.3125 * 1.0) = 2.2857s
        # remaining = 10.0 - 2.2857 = 7.7143s
        # normal autos = floor(1.0 * 7.7143) = 7
        # total = 3 + 7 = 10
        assert autos["empowered_count"] == 3
        assert autos["count"] == 10

    def test_fiendhunter_note_in_result(self) -> None:
        """Fight result should include a note about R assumption."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Fiendhunter Bolts"}],
            one_rotation=True,
        )
        assert len(fight["notes"]) == 1
        assert "Fiendhunter Bolts" in fight["notes"][0]
        assert "R is assumed" in fight["notes"][0]

    def test_fiendhunter_more_damage_than_no_item(self) -> None:
        """Total damage with Fiendhunter should exceed damage without."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        # Use no crits for deterministic comparison
        with patch("src.calculator.damage.random.random", return_value=0.99):
            fight_with = calculate_fight_damage(
                stats,
                abilities,
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                items=[{"name": "Fiendhunter Bolts"}],
                one_rotation=True,
            )
            fight_without = calculate_fight_damage(
                stats,
                abilities,
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                items=[],
                one_rotation=True,
            )
        assert fight_with["total_damage"] > fight_without["total_damage"]

    def test_no_empowered_autos_at_zero_uptime(self) -> None:
        """With 0% auto uptime, no empowered autos and no Fiendhunter effect."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 50,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Fiendhunter Bolts"}],
            one_rotation=True,
        )
        assert fight["breakdown"]["auto_attacks"]["count"] == 0
        assert "fiendhunter_true_damage" not in fight["breakdown"]

    def test_num_crits_in_breakdown(self) -> None:
        """Auto attack breakdown should include num_crits field."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 50,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        # 5 autos, rolls: crit, no crit, crit, no crit, no crit
        rolls = iter([0.1, 0.9, 0.1, 0.9, 0.9])
        with patch("src.calculator.damage.random.random", side_effect=rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                target_health=1000,
                target_armor=0,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                items=[],
                one_rotation=True,
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 2


class TestRagebladeOnHitAllItems:
    """Tests that phantom hits apply ALL on-hit effects, not just Rageblade."""

    BASE_STATS: dict = {
        "attack_damage": 100,
        "ability_power": 0,
        "magic_penetration_flat": 0,
        "magic_penetration_percent": 0,
        "armor_penetration_percent": 0,
        "flat_armor_penetration": 0,
        "critical_strike_chance": 0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "is_melee": True,
        "level": 18,
    }

    def test_rageblade_only_hit_count(self) -> None:
        """Rageblade alone: 7 autos => 7+1=8 on-hit procs for itself."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            target_health=3000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=7.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Guinsoo's Rageblade"}],
        )
        rb = fight["breakdown"].get("on_hit_Guinsoo's Rageblade")
        assert rb is not None
        assert rb["count"] == 8  # 7 normal + 1 phantom

    def test_rageblade_plus_nashors_hit_counts(self) -> None:
        """Both Rageblade and Nashor's should get 8 hits with 7 autos."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            target_health=3000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=7.0,
            auto_attack_uptime=1.0,
            items=[
                {"name": "Guinsoo's Rageblade"},
                {"name": "Nashor's Tooth"},
            ],
        )
        rb = fight["breakdown"]["on_hit_Guinsoo's Rageblade"]
        nt = fight["breakdown"]["on_hit_Nashor's Tooth"]
        assert rb["count"] == 8
        assert nt["count"] == 8  # Nashor's also gets phantom hit bonus

    def test_rageblade_plus_bork_hit_counts(self) -> None:
        """BoRK should get phantom hit procs too (8 hits for 7 autos)."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            target_health=3000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=7.0,
            auto_attack_uptime=1.0,
            items=[
                {"name": "Guinsoo's Rageblade"},
                {"name": "Blade of the Ruined King"},
            ],
        )
        autos = fight["breakdown"]["auto_attacks"]
        rb = fight["breakdown"]["on_hit_Guinsoo's Rageblade"]
        bork = fight["breakdown"]["on_hit_Blade of the Ruined King"]

        assert autos["count"] == 7  # Base auto attacks unchanged
        assert rb["count"] == 8  # Rageblade: 7 + 1 phantom
        assert bork["count"] == 8  # BoRK: 7 + 1 phantom

    def test_bork_phantom_hit_double_procs_at_correct_hp(self) -> None:
        """BoRK phantom hit should proc at current HP after first BoRK hit."""
        # 7 autos, phantom on 6th. BoRK should hit twice on auto #6,
        # with the second hit at a lower HP than the first.
        result, hits = _simulate_bork_damage(
            target_health=3000.0,
            num_auto_attacks=7,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=30.0,  # Rageblade 30 magic dmg
            effective_armor=0.0,
            is_melee=True,
            phantom_hit_autos={5},  # 6th auto (0-indexed)
        )
        assert hits == 8  # 7 normal + 1 phantom
        # Compare to no phantom hits
        result_no_phantom, hits_no = _simulate_bork_damage(
            target_health=3000.0,
            num_auto_attacks=7,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=30.0,
            effective_armor=0.0,
            is_melee=True,
        )
        assert hits_no == 7
        assert result > result_no_phantom

    def test_no_phantom_under_6_autos_with_bork(self) -> None:
        """With 5 autos, no phantom hits — BoRK gets exactly 5 procs."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            target_health=3000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[
                {"name": "Guinsoo's Rageblade"},
                {"name": "Blade of the Ruined King"},
            ],
        )
        rb = fight["breakdown"]["on_hit_Guinsoo's Rageblade"]
        bork = fight["breakdown"]["on_hit_Blade of the Ruined King"]
        assert rb["count"] == 5
        assert bork["count"] == 5

    def test_phantom_hits_in_return_value(self) -> None:
        """Fight result should expose phantom_hit_autos for champion use."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            target_health=3000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Guinsoo's Rageblade"}],
        )
        assert fight["phantom_hit_count"] == 2  # 10 autos: phantom at 6,9
        assert fight["phantom_hit_autos"] == {5, 8}

    def test_ability_on_hit_gets_phantom_procs(self) -> None:
        """Ability on-hit damage should also get phantom hit procs."""
        ability_damages = {
            "passive": {
                "name": "Test Passive",
                "damage_type": "physical",
                "total_raw": 0,
                "on_hit": {
                    "name": "Test Passive (on-hit)",
                    "damage_per_hit": 50.0,
                    "damage_type": "physical",
                },
            },
        }
        fight = calculate_fight_damage(
            self.BASE_STATS,
            ability_damages,
            target_health=3000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=7.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Guinsoo's Rageblade"}],
        )
        passive_oh = fight["breakdown"].get("on_hit_ability_passive")
        assert passive_oh is not None
        assert passive_oh["count"] == 8  # 7 + 1 phantom


class TestKrakenSlayerPhantomHitStacking:
    """Tests that Kraken Slayer gets stack acceleration from phantom hits.

    Phantom hits grant an extra Kraken stack (not an extra damage proc).
    Kraken procs every 3rd stack, and phantom hits can push stacks to 3
    mid-auto to trigger a proc.
    """

    def test_kraken_no_rageblade_normal_stacking(self) -> None:
        """Without Rageblade, Kraken procs every 3rd auto normally."""
        procs, proc_autos = _calculate_kraken_procs(10, set(), 0)
        assert procs == 3  # autos 3, 6, 9
        assert proc_autos == [2, 5, 8]  # 0-indexed

    def test_10_autos_rageblade_4_procs(self) -> None:
        """10 autos + Rageblade (phantoms at 6,9) = 4 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(10, ["Guinsoo's Rageblade"])
        procs, _ = _calculate_kraken_procs(10, phantom_autos, 0)
        assert procs == 4

    def test_12_autos_rageblade_5_procs(self) -> None:
        """12 autos + Rageblade (phantoms at 6,9,12) = 5 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(12, ["Guinsoo's Rageblade"])
        procs, _ = _calculate_kraken_procs(12, phantom_autos, 0)
        assert procs == 5

    def test_15_autos_rageblade_6_procs(self) -> None:
        """15 autos + Rageblade (phantoms at 6,9,12,15) = 6 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(15, ["Guinsoo's Rageblade"])
        procs, _ = _calculate_kraken_procs(15, phantom_autos, 0)
        assert procs == 6

    def test_17_autos_rageblade_7_procs(self) -> None:
        """17 autos + Rageblade (phantoms at 6,9,12,15) = 7 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(17, ["Guinsoo's Rageblade"])
        procs, _ = _calculate_kraken_procs(17, phantom_autos, 0)
        assert procs == 7

    def test_full_fight_kraken_plus_rageblade(self) -> None:
        """Integration test: Kraken + Rageblade in full fight shows correct procs."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "is_melee": True,
            "level": 18,
        }
        fight = calculate_fight_damage(
            stats,
            {},
            target_health=3000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            items=[
                {"name": "Guinsoo's Rageblade"},
                {"name": "Kraken Slayer"},
            ],
        )
        kraken = fight["breakdown"].get("on_hit_Kraken Slayer")
        assert kraken is not None
        assert kraken["procs"] == 4  # 10 autos, phantoms at 6,9

    def test_kraken_damage_scales_with_missing_hp(self) -> None:
        """Later Kraken procs should deal more due to higher missing HP."""
        from src.calculator.damage import _simulate_kraken_damage

        # 9 autos, Kraken procs at autos 3, 6, 9 (indices 2, 5, 8)
        # No armor, melee, level 18 => base = 150 + 5*(18-8) = 200
        # First proc at full HP: missing = 0%, bonus = 1.0x => 200
        # Later procs: target has taken damage, missing > 0%, bonus > 1.0x
        total = _simulate_kraken_damage(
            target_health=3000.0,
            num_auto_attacks=9,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=True,
            level=18,
            kraken_proc_autos=[2, 5, 8],
        )
        # Naive flat (no missing HP bonus): 200 * 3 = 600
        naive_flat = 200.0 * 3
        assert total > naive_flat, (
            f"Simulated {total:.1f} should exceed naive {naive_flat:.1f} "
            f"because later procs benefit from missing HP bonus"
        )

    def test_kraken_first_proc_at_full_hp_is_base_damage(self) -> None:
        """First Kraken proc at full HP should deal base damage (no bonus)."""
        from src.calculator.damage import _simulate_kraken_damage

        # 3 autos, Kraken procs on auto 3 (index 2), no other damage
        total = _simulate_kraken_damage(
            target_health=3000.0,
            num_auto_attacks=3,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=True,
            level=18,
            kraken_proc_autos=[2],
        )
        # At full HP, missing ratio = 0, bonus = 1.0x, damage = 200
        assert abs(total - 200.0) < 0.01

    def test_kraken_base_damage_flat_before_level_9(self) -> None:
        """Base damage should be flat 150 (melee) / 120 (ranged) at levels 1-8."""
        from src.calculator.damage import _simulate_kraken_damage

        for lvl in [1, 5, 8]:
            total = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=True,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert abs(total - 150.0) < 0.01, f"Melee level {lvl}: {total}"

            total_ranged = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=False,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert (
                abs(total_ranged - 120.0) < 0.01
            ), f"Ranged level {lvl}: {total_ranged}"

    def test_kraken_level_scaling_melee(self) -> None:
        """Melee Kraken base: 150 flat until 9, then +5/level."""
        from src.calculator.damage import _simulate_kraken_damage

        expected = {9: 155, 10: 160, 14: 180, 18: 200, 20: 210}
        for lvl, exp in expected.items():
            total = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=True,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert (
                abs(total - exp) < 0.01
            ), f"Melee level {lvl}: got {total}, expected {exp}"

    def test_kraken_level_scaling_ranged(self) -> None:
        """Ranged Kraken base: 120 flat until 9, then +4/level."""
        from src.calculator.damage import _simulate_kraken_damage

        expected = {9: 124, 10: 128, 14: 144, 18: 160, 20: 168}
        for lvl, exp in expected.items():
            total = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=False,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert (
                abs(total - exp) < 0.01
            ), f"Ranged level {lvl}: got {total}, expected {exp}"

    def test_kraken_max_damage_ranged_level_18(self) -> None:
        """Ranged level 18 at 0% target HP should deal 160 * 1.75 = 280."""
        from src.calculator.damage import _simulate_kraken_damage

        # Use very high auto damage to push target to 0 HP before Kraken procs
        total = _simulate_kraken_damage(
            target_health=100.0,
            num_auto_attacks=3,
            auto_damage_per_hit=500.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
            level=18,
            kraken_proc_autos=[2],
        )
        # Target at 0% HP after 2 autos of 500 damage each, missing = 100%
        # Bonus: 1 + 0.75*1.0 = 1.75, damage = 160 * 1.75 = 280
        assert abs(total - 280.0) < 0.01


class TestHeartsteelDamage:
    """Tests for Heartsteel's Colossal Consumption proc."""

    def test_heartsteel_registered_in_item_effects(self) -> None:
        """Heartsteel should be registered with correct type and values."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Heartsteel")
        assert effect is not None
        assert effect["type"] == "on_hit_once"
        assert effect["damage_type"] == "physical"
        assert effect["base"] == 70.0
        assert effect["max_hp_ratio"] == 0.06
        assert effect["cooldown"] == 30.0

    def test_heartsteel_damage_calculation(self) -> None:
        """70 + 6% of 3000 max HP = 70 + 180 = 250 raw physical damage."""
        from src.calculator.item_effects import calculate_heartsteel_damage

        stats = {"health": 3000.0}
        damage = calculate_heartsteel_damage(stats)
        assert abs(damage - 250.0) < 0.01

    def test_heartsteel_damage_low_health(self) -> None:
        """70 + 6% of 1000 max HP = 70 + 60 = 130 raw physical damage."""
        from src.calculator.item_effects import calculate_heartsteel_damage

        stats = {"health": 1000.0}
        damage = calculate_heartsteel_damage(stats)
        assert abs(damage - 130.0) < 0.01

    def test_heartsteel_damage_zero_health(self) -> None:
        """With 0 health the damage is just the base 70."""
        from src.calculator.item_effects import calculate_heartsteel_damage

        stats = {"health": 0.0}
        damage = calculate_heartsteel_damage(stats)
        assert abs(damage - 70.0) < 0.01

    def test_heartsteel_missing_from_effects_returns_zero(self) -> None:
        """If Heartsteel is not in registry, function returns 0."""
        from src.calculator.item_effects import (
            calculate_heartsteel_damage,
            ITEM_EFFECTS,
        )

        original = ITEM_EFFECTS.pop("Heartsteel", None)
        try:
            damage = calculate_heartsteel_damage({"health": 3000.0})
            assert damage == 0.0
        finally:
            if original is not None:
                ITEM_EFFECTS["Heartsteel"] = original


class TestHexopticsC44BasicDamageAmp:
    """Tests for Hexoptics C44 Magnification basic damage amplification."""

    def test_amp_with_item(self) -> None:
        """With Hexoptics C44, amp should be 10% (1.10 multiplier)."""
        from src.calculator.item_effects import get_basic_damage_amplifier

        items = [{"name": "Hexoptics C44"}]
        result = get_basic_damage_amplifier(items)
        assert abs(result - 1.10) < 0.001

    def test_no_amp_without_item(self) -> None:
        """Without Hexoptics C44, basic amp should be 1.0."""
        from src.calculator.item_effects import get_basic_damage_amplifier

        items = [{"name": "Infinity Edge"}]
        result = get_basic_damage_amplifier(items)
        assert result == 1.0

    def test_parsed_values_from_json(self) -> None:
        """Verify parser extracts correct values from item JSON data."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Hexoptics C44")
        assert effect is not None, "Hexoptics C44 not found in ITEM_EFFECTS"
        assert effect["type"] == "basic_damage_amp"
        assert abs(effect["max_amp"] - 0.10) < 0.001
        assert abs(effect["max_distance"] - 500.0) < 0.1

    def test_fight_damage_auto_attacks_amplified(self) -> None:
        """Auto attack damage should be 10% higher with Hexoptics C44."""
        champion_stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.0,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        items_with = [{"name": "Hexoptics C44"}]
        items_without: list[dict] = []

        fight_with = calculate_fight_damage(
            champion_stats,
            {},
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=items_with,
            auto_attacks_only=True,
        )
        fight_without = calculate_fight_damage(
            champion_stats,
            {},
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=items_without,
            auto_attacks_only=True,
        )
        # With Hexoptics, auto damage should be ~10% higher
        ratio = fight_with["total_damage"] / fight_without["total_damage"]
        assert (
            abs(ratio - 1.10) < 0.02
        ), f"Expected ~10% more damage, got ratio {ratio:.3f}"

    def test_breakdown_shows_amplification(self) -> None:
        """Breakdown should include a 'Damage Amplification' entry."""
        champion_stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.0,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        fight = calculate_fight_damage(
            champion_stats,
            {},
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Hexoptics C44"}],
            auto_attacks_only=True,
        )
        amp_entry = fight["breakdown"].get("basic_amp_Hexoptics C44")
        assert amp_entry is not None, "Missing basic_amp breakdown entry"
        assert amp_entry["name"] == "Damage Amplification (Hexoptics C44)"
        assert amp_entry["total_damage"] > 0


class TestHorizonFocusHypershotAmp:
    """Tests for Horizon Focus Hypershot damage amplification."""

    def test_parsed_values_from_json(self) -> None:
        """Verify parser extracts correct amp value from item JSON data."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Horizon Focus")
        assert effect is not None, "Horizon Focus not found in ITEM_EFFECTS"
        assert effect["type"] == "hypershot_amp"
        assert abs(effect["amp"] - 0.10) < 0.001

    def test_amplifier_with_item(self) -> None:
        """With Horizon Focus, hypershot amp should be 1.10."""
        from src.calculator.item_effects import get_hypershot_amplifier

        items = [{"name": "Horizon Focus"}]
        result = get_hypershot_amplifier(items)
        assert abs(result - 1.10) < 0.001

    def test_amplifier_without_item(self) -> None:
        """Without Horizon Focus, hypershot amp should be 1.0."""
        from src.calculator.item_effects import get_hypershot_amplifier

        items = [{"name": "Liandry's Torment"}]
        result = get_hypershot_amplifier(items)
        assert result == 1.0

    def test_first_ability_not_amped(self) -> None:
        """First ability triggers the mark and should NOT be amplified."""
        stats = {
            "attack_damage": 60.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.6,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 100.0,
            "is_melee": False,
            "level": 9,
        }
        # Two abilities: Q (trigger) and E (amped)
        abilities = {
            "Q": {
                "name": "Test Q",
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 6.0,
            },
            "E": {
                "name": "Test E",
                "total_raw": 150.0,
                "damage_type": "magic",
                "cooldown": 8.0,
            },
        }

        # Without Horizon Focus
        fight_base = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=0,
            fight_duration_seconds=0.5,
            auto_attack_uptime=0.0,
            items=[],
            one_rotation=True,
            cast_order=["Q", "E"],
        )

        # With Horizon Focus
        fight_hf = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=0,
            fight_duration_seconds=0.5,
            auto_attack_uptime=0.0,
            items=[{"name": "Horizon Focus"}],
            one_rotation=True,
            cast_order=["Q", "E"],
        )

        # Q does 200, E does 150, both at 0 MR so no mitigation.
        # Horizon Focus should amp E (150) by 10% = +15, but NOT amp Q.
        q_base = fight_base["breakdown"]["Q"]["total_damage"]
        q_hf = fight_hf["breakdown"]["Q"]["total_damage"]
        # Q damage itself should be the same (not amped inline)
        assert (
            abs(q_base - q_hf) < 0.01
        ), f"Q should not change: base={q_base:.1f} vs hf={q_hf:.1f}"

        # The amp entry should exist and NOT include Q damage
        amp_entry = fight_hf["breakdown"].get("damage_amp_Horizon Focus")
        assert amp_entry is not None, "Missing Horizon Focus breakdown entry"
        assert amp_entry["name"] == "Damage Amplification (Horizon Focus)"
        # Bonus should be ~10% of non-Q damage (E = 150)
        assert (
            abs(amp_entry["total_damage"] - 15.0) < 1.0
        ), f"Expected ~15 bonus, got {amp_entry['total_damage']:.1f}"

    def test_mixed_ability_only_first_hit_excluded(self) -> None:
        """For mixed abilities (Ahri Q), only the first hit is the trigger.

        Ahri Q deals magic (outgoing) + true (return). Only the magic
        outgoing hit triggers Hypershot; the true return hit should be amped.
        """
        stats = {
            "attack_damage": 60.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.6,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 9,
        }
        # Simulate Ahri Q: mixed (magic out + true return), 100 each
        abilities = {
            "Q": {
                "name": "Orb of Deception",
                "magic_damage": 100.0,
                "true_damage": 100.0,
                "total_raw": 200.0,
                "damage_type": "mixed",
                "cooldown": 7.0,
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=0,
            fight_duration_seconds=0.5,
            auto_attack_uptime=0.0,
            items=[{"name": "Horizon Focus"}],
            one_rotation=True,
            cast_order=["Q"],
        )

        # At 0 MR: magic_damage = 100, true_damage = 100, total Q = 200.
        # First hit (magic, 100) triggers Hypershot — NOT amped.
        # Return hit (true, 100) IS amped.
        # So amped_damage = 200 - 100 = 100, bonus = 100 * 0.10 = 10.
        amp_entry = fight["breakdown"].get("damage_amp_Horizon Focus")
        assert amp_entry is not None, "Missing Horizon Focus breakdown"
        assert abs(amp_entry["total_damage"] - 10.0) < 1.0, (
            f"Expected ~10 bonus (return hit only), got "
            f"{amp_entry['total_damage']:.1f}"
        )


class TestHullbreakerSkipper:
    """Tests for Hullbreaker Skipper stacking on-hit proc."""

    def test_parsed_values_from_json(self) -> None:
        """Verify parser extracts correct values from item JSON data."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Hullbreaker")
        assert effect is not None, "Hullbreaker not found in ITEM_EFFECTS"
        assert effect["type"] == "on_hit_stacking"
        assert abs(effect["base_ad_ratio_melee"] - 1.20) < 0.001
        assert abs(effect["base_ad_ratio_ranged"] - 0.84) < 0.001
        assert abs(effect["max_hp_ratio_melee"] - 0.05) < 0.001
        assert abs(effect["max_hp_ratio_ranged"] - 0.035) < 0.001
        assert effect["hits_required"] == 5

    def test_proc_damage_melee(self) -> None:
        """Melee proc: 120% base AD + 5% max HP."""
        from src.calculator.item_effects import calculate_hullbreaker_proc_damage

        stats = {"base_attack_damage": 100.0, "health": 2000.0}
        damage = calculate_hullbreaker_proc_damage(stats, is_melee=True)
        # 1.20 * 100 + 0.05 * 2000 = 120 + 100 = 220
        assert abs(damage - 220.0) < 0.1

    def test_proc_damage_ranged(self) -> None:
        """Ranged proc: 84% base AD + 3.5% max HP."""
        from src.calculator.item_effects import calculate_hullbreaker_proc_damage

        stats = {"base_attack_damage": 100.0, "health": 2000.0}
        damage = calculate_hullbreaker_proc_damage(stats, is_melee=False)
        # 0.84 * 100 + 0.035 * 2000 = 84 + 70 = 154
        assert abs(damage - 154.0) < 0.1

    def test_stacking_procs_5_hits(self) -> None:
        """5 autos should yield exactly 1 proc."""
        procs, proc_autos = _calculate_hullbreaker_procs(5, set())
        assert procs == 1
        assert proc_autos == [4]  # 0-indexed, 5th auto

    def test_stacking_procs_10_hits(self) -> None:
        """10 autos should yield exactly 2 procs."""
        procs, _ = _calculate_hullbreaker_procs(10, set())
        assert procs == 2

    def test_stacking_procs_4_hits_no_proc(self) -> None:
        """4 autos should yield 0 procs."""
        procs, _ = _calculate_hullbreaker_procs(4, set())
        assert procs == 0

    def test_phantom_hit_adds_stack_not_damage(self) -> None:
        """Phantom hit accelerates stacking but doesn't duplicate proc."""
        # 5 autos, phantom on auto #3 (0-indexed). Stacks:
        #   auto 0: 1, auto 1: 2, auto 2: 3, auto 3: 4+1(phantom)=5 -> proc
        #   auto 4: 1
        # Should get 1 proc on auto 3 (earlier than without phantom)
        procs, proc_autos = _calculate_hullbreaker_procs(5, {3})
        assert procs == 1
        assert 3 in proc_autos  # Proc fires on auto 3, not 4

    def test_fight_damage_with_hullbreaker(self) -> None:
        """Integration: Hullbreaker procs appear in fight breakdown."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 80.0,
            "attack_speed": 1.0,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "health": 2000.0,
            "is_melee": True,
            "level": 10,
        }
        fight = calculate_fight_damage(
            stats,
            {},
            target_health=3000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Hullbreaker"}],
            auto_attacks_only=True,
        )
        hb_entry = fight["breakdown"].get("on_hit_Hullbreaker")
        assert hb_entry is not None, "Missing Hullbreaker breakdown entry"
        assert hb_entry["name"] == "Hullbreaker (Skipper)"
        assert hb_entry["procs"] >= 1
        assert hb_entry["total_damage"] > 0


class TestMuramanaMultiCastR:
    """Tests for Muramana ability procs on multi-cast abilities like Ahri R."""

    def test_r_procs_muramana_per_dash(self) -> None:
        """Ahri R has 3 dashes — Muramana should proc 3 times, not 1."""
        from src.calculator.item_effects import get_muramana_ability_damage

        stats = {
            "attack_damage": 80.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.7,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 100.0,
            "max_mana": 1500.0,
            "is_melee": False,
            "level": 18,
        }

        # Only R: 3 sub-casts
        abilities = {
            "R": {
                "name": "Spirit Rush",
                "damage_per_cast": 200.0,
                "total_casts": 3,
                "total_raw": 600.0,
                "damage_type": "magic",
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=1.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Muramana"}],
            one_rotation=True,
            cast_order=["R"],
        )

        mura_entry = fight["breakdown"].get("muramana_ability")
        assert mura_entry is not None, "Missing Muramana ability breakdown"

        # Muramana ranged ability: 3% max mana per proc * 3 procs
        # = 0.03 * 1500 * 3 = 135 raw physical damage
        per_proc = get_muramana_ability_damage(stats, False, 1)
        expected_raw = per_proc * 3
        # After 100 armor: 50% mitigation
        expected_mitigated = expected_raw * 0.5
        assert abs(mura_entry["total_damage"] - expected_mitigated) < 1.0, (
            f"Expected ~{expected_mitigated:.1f}, got "
            f"{mura_entry['total_damage']:.1f}"
        )

    def test_single_cast_ability_procs_once(self) -> None:
        """A normal single-cast ability should proc Muramana once."""
        stats = {
            "attack_damage": 80.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.7,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 100.0,
            "max_mana": 1500.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=1.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Muramana"}],
            one_rotation=True,
            cast_order=["Q"],
        )

        mura_entry = fight["breakdown"].get("muramana_ability")
        assert mura_entry is not None
        # 1 proc: 0.03 * 1500 = 45 raw, mitigated by 100 armor = 22.5
        assert abs(mura_entry["total_damage"] - 22.5) < 1.0


class TestNavoriFlickerbladeFight:
    """Integration tests for Navori CD refund in fight calculations."""

    def test_more_casts_with_navori(self) -> None:
        """Navori should produce more ability casts than without."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight_no_navori = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=15.0,
            auto_attack_uptime=0.8,
            items=[],
            cast_order=["Q"],
        )
        fight_navori = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=15.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Navori Flickerblade"}],
            cast_order=["Q"],
        )

        q_no = fight_no_navori["breakdown"]["Q"]["casts"]
        q_nav = fight_navori["breakdown"]["Q"]["casts"]
        assert q_nav > q_no, f"Navori should give more casts: {q_nav} vs {q_no} without"

    def test_r_not_affected(self) -> None:
        """R is always 1 cast — Navori should not change it."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "R": {
                "name": "Test R",
                "damage_per_cast": 100.0,
                "total_casts": 3,
                "total_raw": 300.0,
                "damage_type": "magic",
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=15.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Navori Flickerblade"}],
            cast_order=["R"],
        )
        assert fight["breakdown"]["R"]["casts"] == 1

    def test_no_effect_in_one_rotation(self) -> None:
        """In one-rotation mode, Navori should not add extra casts."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=15.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Navori Flickerblade"}],
            one_rotation=True,
            cast_order=["Q"],
        )
        assert fight["breakdown"]["Q"]["casts"] == 1

    def test_no_effect_without_autos(self) -> None:
        """With 0 uptime, Navori has no autos to refund with."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight_no = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=15.0,
            auto_attack_uptime=0.0,
            items=[],
            cast_order=["Q"],
        )
        fight_nav = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=15.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Navori Flickerblade"}],
            cast_order=["Q"],
        )
        assert (
            fight_no["breakdown"]["Q"]["casts"] == fight_nav["breakdown"]["Q"]["casts"]
        )


class TestNewItemDamageEffects:
    """Integration tests for newly implemented item damage effects."""

    def _make_stats(self, **overrides: float) -> dict[str, float]:
        """Create a minimal champion stats dict."""
        stats = {
            "health": 2000.0,
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "bonus_health": 0.0,
            "lethality": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "critical_strike_chance": 0.0,
            "max_mana": 500.0,
            "bonus_mana": 0.0,
            "ability_haste": 0.0,
            "basic_ability_haste": 0.0,
            "level": 18,
            "is_melee": True,
        }
        stats.update(overrides)
        return stats

    def test_stormrazor_first_auto_damage(self) -> None:
        """Stormrazor deals 100 magic damage on first auto (one proc)."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Stormrazor"}],
        )
        assert "on_hit_once_Stormrazor" in result["breakdown"]
        entry = result["breakdown"]["on_hit_once_Stormrazor"]
        assert entry["damage_type"] == "magic"
        assert entry["total_damage"] > 0

    def test_statikk_shiv_one_empowered_auto(self) -> None:
        """Reworked Electrospark: ONE empowered auto deals 60 magic damage
        (single-target: the chain lightning has nothing to bounce to)."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Statikk Shiv"}],
        )
        assert "on_hit_once_Statikk Shiv" in result["breakdown"]
        entry = result["breakdown"]["on_hit_once_Statikk Shiv"]
        assert entry["procs"] == 1
        assert entry["damage_type"] == "magic"

    def test_statikk_shiv_no_autos_no_proc(self) -> None:
        """Without any auto attacks there is no Electrospark proc."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=1.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Statikk Shiv"}],
        )
        assert "on_hit_once_Statikk Shiv" not in result["breakdown"]

    def test_titanic_hydra_active_in_breakdown(self) -> None:
        """Titanic Hydra Crescent active appears in fight breakdown."""
        stats = self._make_stats(health=3000.0)
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Titanic Hydra"}],
        )
        assert "active_Titanic Hydra" in result["breakdown"]
        entry = result["breakdown"]["active_Titanic Hydra"]
        assert entry["damage_type"] == "physical"
        # 4% of 3000 HP = 120 raw per proc
        assert entry["total_damage"] > 0

    def test_spear_of_shojin_basic_haste_reduces_q_cd(self) -> None:
        """Basic ability haste reduces Q/W/E cooldowns but not R.

        Verifies via effective_cooldown formula:
        - Q at 6s base, 0 ability haste, 25 basic = 6 * 100/125 = 4.8s
        - R at 60s base, 0 ability haste, 25 basic = still 60s (no basic haste)
        """
        from src.calculator.champions.common import effective_cooldown

        base_q_cd = 6.0
        base_r_cd = 60.0
        ability_haste = 0.0
        basic_haste = 25.0

        # Q with basic ability haste should be shorter
        q_no_basic = effective_cooldown(base_q_cd, ability_haste)
        q_with_basic = effective_cooldown(base_q_cd, ability_haste + basic_haste)
        assert q_with_basic < q_no_basic
        assert abs(q_with_basic - 4.8) < 0.01

        # R should NOT use basic ability haste
        r_cd = effective_cooldown(base_r_cd, ability_haste)
        assert abs(r_cd - 60.0) < 0.01


class TestSunderedSky:
    """Tests for Sundered Sky first-auto crit modifier."""

    def _make_stats(self, **overrides: float) -> dict[str, float]:
        """Create a minimal champion stats dict."""
        stats = {
            "health": 2000.0,
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "bonus_health": 0.0,
            "lethality": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "critical_strike_chance": 0.0,
            "max_mana": 500.0,
            "bonus_mana": 0.0,
            "ability_haste": 0.0,
            "basic_ability_haste": 0.0,
            "level": 18,
            "is_melee": True,
        }
        stats.update(overrides)
        return stats

    def test_sundered_sky_first_auto_crits(self) -> None:
        """First auto with Sundered Sky always crits at reduced ratio."""
        stats = self._make_stats(critical_strike_chance=0.0)
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=0,
            target_magic_resistance=50,
            fight_duration_seconds=1.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Sundered Sky"}],
        )
        auto_entry = result["breakdown"]["auto_attacks"]
        # With 0% crit chance and 1 auto attack, the first auto should
        # still deal more than base AD because of Sundered Sky crit
        assert auto_entry["total_damage"] > 100.0

    def test_sundered_sky_overrides_natural_crit(self) -> None:
        """Even with 100% crit chance, Sundered Sky overrides first auto.

        With 100% crit, normal crit = 200% AD = 200 damage.
        Sundered Sky = 80% of crit = 80% * 200% = 160% AD = 160.
        So Sundered Sky first auto should deal LESS than a normal crit.
        """
        stats = self._make_stats(critical_strike_chance=100.0)
        # Many autos to average: first auto is Sundered Sky, rest are normal crits
        result = calculate_fight_damage(
            stats,
            {},
            target_health=5000,
            target_armor=0,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Sundered Sky"}],
        )
        auto_entry = result["breakdown"]["auto_attacks"]
        # With 100% crit and 0 armor, normal crit = 200. SS auto = 160.
        # Total should be less than all_crits * count
        count = auto_entry["count"]
        all_normal_crits = 200.0 * count
        assert auto_entry["total_damage"] < all_normal_crits

    def test_sundered_sky_reads_from_registry(self, monkeypatch) -> None:
        """Sundered Sky uses ITEM_EFFECTS registry, not hardcoded values."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("Sundered Sky", {}))
        patched["reduced_crit_ratio"] = 0.50  # 50% instead of 80%
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Sundered Sky", patched)

        stats = self._make_stats(critical_strike_chance=0.0)
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=0,
            target_magic_resistance=50,
            fight_duration_seconds=2.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Sundered Sky"}],
        )
        auto_entry = result["breakdown"]["auto_attacks"]
        # First auto: 50% of crit_multiplier(2.0) = 1.0 * 100 AD = 100
        # Second auto: normal (no crit) = 100
        # Total = 200, average = 100
        assert auto_entry["count"] == 2
        assert auto_entry["total_damage"] == 200.0

    def test_sundered_sky_parsed_values(self) -> None:
        """Parser extracts reduced_crit_ratio and cooldown from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Sundered Sky", items)
        assert parsed is not None
        assert parsed["reduced_crit_ratio"] == 0.80
        assert parsed["cooldown"] == 10.0


class TestVoltaicCyclosword:
    """Tests for Voltaic Cyclosword energized first-auto damage."""

    def _make_stats(self, **overrides: float) -> dict[str, float]:
        stats = {
            "health": 2000.0,
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "bonus_health": 0.0,
            "lethality": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "critical_strike_chance": 0.0,
            "max_mana": 500.0,
            "bonus_mana": 0.0,
            "ability_haste": 0.0,
            "basic_ability_haste": 0.0,
            "level": 18,
            "is_melee": True,
        }
        stats.update(overrides)
        return stats

    def test_voltaic_first_auto_damage(self) -> None:
        """Voltaic Cyclosword deals physical damage on first auto."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Voltaic Cyclosword"}],
        )
        assert "on_hit_once_Voltaic Cyclosword" in result["breakdown"]
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        assert entry["damage_type"] == "physical"
        assert entry["total_damage"] > 0

    def test_voltaic_only_one_proc(self) -> None:
        """Even with many autos, Voltaic Cyclosword only procs once.

        Melee vs 5000 HP: 9% current HP = 450. The wiki's 200 cap applies
        to non-champions only; the calculator targets champions, so no cap.
        """
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=5000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=20.0,
            auto_attack_uptime=1.0,
            items=[{"name": "Voltaic Cyclosword"}],
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        # Damage should be a single uncapped proc, not multiplied by autos
        from src.calculator.resistance import apply_resistance

        expected = apply_resistance(450.0, result["effective_armor"])
        assert abs(entry["total_damage"] - expected) < 1.0

    def test_voltaic_current_hp_below_cap(self) -> None:
        """Melee vs 2000 HP: 9% current HP = 180, under the 200 cap."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=0,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Voltaic Cyclosword"}],
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        assert entry["total_damage"] == pytest.approx(180.0)

    def test_voltaic_ranged_ratio(self) -> None:
        """Ranged vs 2000 HP: 7% current HP = 140."""
        stats = self._make_stats(is_melee=False)
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=0,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Voltaic Cyclosword"}],
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        assert entry["total_damage"] == pytest.approx(140.0)

    def test_voltaic_parsed_values(self) -> None:
        """Parser extracts the reworked Firmament: current-HP physical damage
        (melee 9% / ranged 7%) capped at 200."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Voltaic Cyclosword", items)
        assert parsed is not None
        assert parsed["current_hp_ratio_melee"] == pytest.approx(0.09)
        assert parsed["current_hp_ratio_ranged"] == pytest.approx(0.07)
        assert parsed["damage_cap"] == 200.0
        assert parsed["damage_type"] == "physical"

    def test_voltaic_reads_from_registry(self, monkeypatch) -> None:
        """Voltaic Cyclosword uses ITEM_EFFECTS registry."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("Voltaic Cyclosword", {}))
        patched["current_hp_ratio_melee"] = 0.10
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Voltaic Cyclosword", patched)

        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=0,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Voltaic Cyclosword"}],
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        # 10% of 2000 = 200 (patched ratio, zero armor)
        assert entry["total_damage"] == 200.0


class TestUnendingDespair:
    """Tests for Unending Despair periodic AoE damage."""

    def _make_stats(self, **overrides: float) -> dict[str, float]:
        stats = {
            "health": 3000.0,
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "bonus_health": 1000.0,
            "lethality": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "critical_strike_chance": 0.0,
            "max_mana": 500.0,
            "bonus_mana": 0.0,
            "ability_haste": 0.0,
            "basic_ability_haste": 0.0,
            "level": 18,
            "is_melee": True,
        }
        stats.update(overrides)
        return stats

    def test_unending_despair_in_breakdown(self) -> None:
        """Unending Despair Anguish appears in fight breakdown."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Unending Despair"}],
        )
        assert "periodic_Unending Despair" in result["breakdown"]
        entry = result["breakdown"]["periodic_Unending Despair"]
        assert entry["damage_type"] == "magic"
        assert entry["total_damage"] > 0

    def test_unending_despair_proc_count(self) -> None:
        """Procs at 4s intervals: 10s fight = 2 procs (at 4s and 8s)."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=0,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Unending Despair"}],
        )
        entry = result["breakdown"]["periodic_Unending Despair"]
        # 2 procs * 3% of 1000 bonus HP = 2 * 30 = 60 raw magic damage
        # 0 MR = 60 mitigated
        assert abs(entry["total_damage"] - 60.0) < 1.0

    def test_unending_despair_no_bonus_health_no_damage(self) -> None:
        """With 0 bonus health, Anguish deals no damage."""
        stats = self._make_stats(bonus_health=0.0)
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Unending Despair"}],
        )
        assert "periodic_Unending Despair" not in result["breakdown"]

    def test_unending_despair_parsed_values(self) -> None:
        """Parser extracts interval and bonus_hp_ratio from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Unending Despair", items)
        assert parsed is not None
        assert parsed["interval"] == 4.0
        assert parsed["bonus_hp_ratio"] == 0.03

    def test_unending_despair_reads_from_registry(self, monkeypatch) -> None:
        """Unending Despair uses ITEM_EFFECTS registry."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("Unending Despair", {}))
        patched["bonus_hp_ratio"] = 0.10  # 10% instead of 3%
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Unending Despair", patched)

        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=0,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Unending Despair"}],
        )
        entry = result["breakdown"]["periodic_Unending Despair"]
        # 2 procs * 10% of 1000 bonus HP = 200 raw
        assert abs(entry["total_damage"] - 200.0) < 1.0


class TestTerminusPenetration:
    """Tests for Terminus armor/magic penetration stacking."""

    def _make_stats(self, **overrides: float) -> dict[str, float]:
        stats = {
            "health": 2000.0,
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "bonus_health": 0.0,
            "lethality": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "critical_strike_chance": 0.0,
            "max_mana": 500.0,
            "bonus_mana": 0.0,
            "ability_haste": 0.0,
            "basic_ability_haste": 0.0,
            "level": 18,
            "is_melee": True,
        }
        stats.update(overrides)
        return stats

    def test_terminus_pen_reduces_effective_armor(self) -> None:
        """Terminus pen reduces effective armor vs no Terminus."""
        stats = self._make_stats()
        result_no_terminus = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=100,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[],
        )
        result_with_terminus = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=100,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Terminus"}],
        )
        # With Terminus pen, effective armor should be lower
        assert (
            result_with_terminus["effective_armor"]
            < result_no_terminus["effective_armor"]
        )

    def test_terminus_pen_increases_total_damage(self) -> None:
        """Terminus pen should increase total damage dealt."""
        stats = self._make_stats()
        result_no = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[],
        )
        result_with = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Terminus"}],
        )
        assert result_with["total_damage"] > result_no["total_damage"]

    def test_terminus_pen_average_12_autos(self) -> None:
        """12 autos: pen per auto = 0,10,10,20,20,30,30,30,30,30,30,30.

        Average = 270/12 = 22.5%.
        """
        from src.calculator.item_effects import get_terminus_pen_stacks

        avg_pen = get_terminus_pen_stacks(12)
        assert abs(avg_pen - 0.225) < 0.001

    def test_terminus_pen_6_autos(self) -> None:
        """6 autos: pen = 0,10,10,20,20,30 → avg = 90/6 = 15%."""
        from src.calculator.item_effects import get_terminus_pen_stacks

        assert abs(get_terminus_pen_stacks(6) - 0.15) < 0.001

    def test_terminus_pen_2_autos(self) -> None:
        """2 autos: pen = 0,10 → avg = 5%."""
        from src.calculator.item_effects import get_terminus_pen_stacks

        assert abs(get_terminus_pen_stacks(2) - 0.05) < 0.001

    def test_terminus_pen_4_autos(self) -> None:
        """4 autos: pen = 0,10,10,20 → avg = 40/4 = 10%."""
        from src.calculator.item_effects import get_terminus_pen_stacks

        assert abs(get_terminus_pen_stacks(4) - 0.10) < 0.001

    def test_terminus_pen_zero_autos_no_pen(self) -> None:
        """With 0 autos, no pen stacks."""
        from src.calculator.item_effects import get_terminus_pen_stacks

        assert get_terminus_pen_stacks(0) == 0.0

    def test_terminus_pen_one_auto_no_pen(self) -> None:
        """With 1 auto, no dark hits (dark = every other auto)."""
        from src.calculator.item_effects import get_terminus_pen_stacks

        assert get_terminus_pen_stacks(1) == 0.0

    def test_terminus_pen_caps_at_30_long_fight(self) -> None:
        """With many autos, average pen approaches 30% but never exceeds."""
        from src.calculator.item_effects import get_terminus_pen_stacks

        avg = get_terminus_pen_stacks(100)
        assert avg < 0.30
        assert avg > 0.28  # Should be close to 30%

    def test_terminus_pen_parsed_values(self) -> None:
        """Parser extracts dark_pen_per_stack and dark_max_stacks."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Terminus", items)
        assert parsed is not None
        assert parsed["dark_pen_per_stack"] == 0.10
        assert parsed["dark_max_stacks"] == 3


class TestCollectorThreshold:
    """Tests for The Collector execution threshold display."""

    def _make_stats(self, **overrides: float) -> dict[str, float]:
        stats = {
            "health": 2000.0,
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "bonus_health": 0.0,
            "lethality": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "critical_strike_chance": 0.0,
            "max_mana": 500.0,
            "bonus_mana": 0.0,
            "ability_haste": 0.0,
            "basic_ability_haste": 0.0,
            "level": 18,
            "is_melee": True,
        }
        stats.update(overrides)
        return stats

    def test_collector_shows_threshold_not_damage(self) -> None:
        """Collector shows execution threshold but adds 0 damage."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "The Collector"}],
        )
        assert "execute" in result["breakdown"]
        entry = result["breakdown"]["execute"]
        assert entry["total_damage"] == 0.0
        assert entry["execution_threshold_hp"] == 100.0  # 5% of 2000
        assert "Collector Execution Threshold" in entry["note"]

    def test_collector_threshold_scales_with_target_health(self) -> None:
        """Threshold scales with target max health."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=4000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "The Collector"}],
        )
        entry = result["breakdown"]["execute"]
        assert entry["execution_threshold_hp"] == 200.0  # 5% of 4000

    def test_collector_parsed_values(self) -> None:
        """Parser extracts threshold from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("The Collector", items)
        assert parsed is not None
        assert parsed["threshold"] == 0.05

    def test_collector_reads_from_registry(self, monkeypatch) -> None:
        """Collector threshold uses ITEM_EFFECTS registry."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("The Collector", {}))
        patched["threshold"] = 0.10  # 10% instead of 5%
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "The Collector", patched)

        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "The Collector"}],
        )
        entry = result["breakdown"]["execute"]
        assert entry["execution_threshold_hp"] == 200.0  # 10% of 2000
