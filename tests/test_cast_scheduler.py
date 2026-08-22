"""The timed cast scheduler: variant-slot haste, ultimate recasts, autos-only.

These pin the three scheduler decisions the surface-area campaign found
(backlog CF2, CF18, CF23) at the engine boundary, where a synthetic kit can
name a slot no cached champion emits today.
"""

from src.calculator import damage
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
        "parts": (),
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
        """``R_buff`` is an R: ultimate haste shortens its cooldown."""
        abilities = {"R_buff": _slot_row("Ultimate buff", 10.0)}
        order = ["R_buff"]
        plain = _timed(attacker_stats(), dict(abilities), cast_order=order)[
            "breakdown"
        ]["R_buff"]["casts"]
        hasted = _timed(
            attacker_stats(ultimate_haste=100.0), dict(abilities), cast_order=order
        )["breakdown"]["R_buff"]["casts"]
        assert (plain, hasted) == (3, 5)
