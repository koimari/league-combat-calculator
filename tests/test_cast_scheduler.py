"""The timed cast scheduler: variant-slot haste, ultimate recasts, autos-only.

These pin the three scheduler decisions the surface-area campaign found
(backlog CF2, CF18, CF23) at the engine boundary, where a synthetic kit can
name a slot no cached champion emits today.
"""

from src.calculator import damage
from src.calculator.ability_spec import DamagePart
from src.calculator.champions import (
    get_champion_ultimate_recasts,
    registered_champion_names,
)
from src.calculator.damage import FightConfig, calculate_fight_damage


def _timed(stats, abilities, **overrides):
    """A 20-second timed fight over a synthetic kit."""
    config = {
        "target_health": 10000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 20.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    items = config.pop("items", [])
    return calculate_fight_damage(stats, abilities, items, FightConfig(**config))


def _slot_row(name, cooldown, amount=100.0):
    return {
        "name": name,
        "rank": 5,
        "cooldown": cooldown,
        "cast_time": 0.0,
        "damage_type": "physical",
        "total_raw": amount,
        "parts": (DamagePart("physical", amount),),
    }


class TestVariantSlotHaste:
    """CF2: a variant slot key earns its BASE slot's haste."""

    def test_base_slot_resolves_variant_keys(self):
        assert damage._base_slot("W_frenzy") == "W"
        assert damage._base_slot("Q2") == "Q"
        assert damage._base_slot("R_onhit") == "R"
        assert damage._base_slot("passive") == "passive"

    def test_shojin_haste_reaches_a_variant_basic_slot(self, attacker_stats):
        """``W_frenzy`` is a W: Spear-of-Shojin haste shortens its cooldown."""
        abilities = {"W_frenzy": _slot_row("Frenzy", 10.0)}
        order = ["W_frenzy"]
        plain = _timed(attacker_stats(), dict(abilities), cast_order=order)[
            "breakdown"
        ]["W_frenzy"]["casts"]
        hasted = _timed(
            attacker_stats(basic_ability_haste=100.0),
            dict(abilities),
            cast_order=order,
        )["breakdown"]["W_frenzy"]["casts"]
        # 10s -> 5s over a 20s window (a cast counts if it STARTS in it).
        assert (plain, hasted) == (3, 5)

    def test_ultimate_haste_reaches_a_variant_ultimate_slot(self, attacker_stats):
        """``R_buff`` is an R: it obeys the ultimate rule AND earns its haste."""
        abilities = {"R_buff": _slot_row("Ultimate buff", 10.0)}
        order = ["R_buff"]
        # Resolving the variant to its base slot also puts it under the
        # one-cast rule, which the raw-key branch let it escape.
        assert (
            _timed(attacker_stats(), dict(abilities), cast_order=order)["breakdown"][
                "R_buff"
            ]["casts"]
            == 1
        )
        certified = {"cast_order": order, "ultimate_recasts": True}
        plain = _timed(attacker_stats(), dict(abilities), **certified)["breakdown"][
            "R_buff"
        ]["casts"]
        hasted = _timed(
            attacker_stats(ultimate_haste=100.0), dict(abilities), **certified
        )["breakdown"]["R_buff"]["casts"]
        assert (plain, hasted) == (3, 5)


class TestUltimateRecastCertification:
    """CF18: an ultimate recasts only for a module that certifies it."""

    def test_an_uncertified_ultimate_casts_once(self, attacker_stats):
        abilities = {"R": _slot_row("Ultimate", 5.0)}
        result = _timed(attacker_stats(), abilities, cast_order=["R"])
        assert result["breakdown"]["R"]["casts"] == 1

    def test_a_certified_ultimate_recasts_on_its_hasted_cooldown(self, attacker_stats):
        abilities = {"R": _slot_row("Ultimate", 10.0)}
        certified = {"cast_order": ["R"], "ultimate_recasts": True}
        plain = _timed(attacker_stats(), dict(abilities), **certified)
        hasted = _timed(
            attacker_stats(ultimate_haste=100.0), dict(abilities), **certified
        )
        assert plain["breakdown"]["R"]["casts"] == 3
        assert hasted["breakdown"]["R"]["casts"] == 5
        assert hasted["total_damage"] > plain["total_damage"]

    def test_the_one_cast_rule_is_disclosed_when_it_binds(self, attacker_stats):
        """A cooldown that fits the window says so; one that cannot stays quiet."""
        fits = _timed(
            attacker_stats(), {"R": _slot_row("Ultimate", 10.0)}, cast_order=["R"]
        )
        assert any("is cast once" in note for note in fits["notes"])
        outlasts = _timed(
            attacker_stats(), {"R": _slot_row("Ultimate", 120.0)}, cast_order=["R"]
        )
        assert not any("is cast once" in note for note in outlasts["notes"])


class TestBlitzcrankCertification:
    """Static Field is the reviewed certification, read off the contract."""

    def test_blitzcrank_certifies_and_the_rest_do_not(self):
        certified = sorted(
            name
            for name in registered_champion_names()
            if get_champion_ultimate_recasts(name)
        )
        assert certified == ["Blitzcrank"]
        assert get_champion_ultimate_recasts("Nobody") is False


class TestAutosOnlyBuysNoSteroid:
    """CF23: autos-only performs no cast, so it earns no cast's stat grant."""

    @staticmethod
    def _steroid_kit():
        row = _slot_row("Rapid Fire", 20.0)
        row["stat_buff"] = {"bonus_attack_speed": 100.0}
        return {"Q": row}

    @staticmethod
    def _fight(attacker_stats, abilities, order, **overrides):
        """The engine buffs the stats dict in place, so hold on to it."""
        stats = attacker_stats()
        result = _timed(
            stats,
            abilities,
            cast_order=order,
            auto_attack_uptime=1.0,
            **overrides,
        )
        return stats, result

    def test_a_timed_fight_still_buys_the_grant(self, attacker_stats):
        stats, _ = self._fight(attacker_stats, self._steroid_kit(), ["Q"])
        assert stats["attack_speed"] == 1.625

    def test_autos_only_keeps_the_unbuffed_attack_speed(self, attacker_stats):
        stats, result = self._fight(
            attacker_stats, self._steroid_kit(), ["Q"], auto_attacks_only=True
        )
        assert stats["attack_speed"] == 1.0
        assert any(
            "Autos-only performs no cast" in note and "Rapid Fire" in note
            for note in result["notes"]
        )

    def test_a_passive_grant_survives_autos_only(self, attacker_stats):
        """The mode drops casts, not the kit: an innate is still innate."""
        row = _slot_row("Innate", 0.0)
        row["stat_buff"] = {"bonus_attack_speed": 100.0}
        stats, result = self._fight(
            attacker_stats, {"passive": row}, [], auto_attacks_only=True
        )
        assert stats["attack_speed"] == 1.625
        assert not any("Autos-only performs no cast" in n for n in result["notes"])
