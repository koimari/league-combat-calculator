"""E4-1 summoned-unit damage — batch 1 (Annie, Heimerdinger, Malzahar, Azir, Illaoi).

One test per champion drives an ``/api/calculate`` fight at level 18
(basic abilities rank 5, ultimates rank 3, no items, target armor/MR 0 so
post-mitigation damage equals the raw wiki values) and asserts the pet
damage row against values recomputed from ``data/champions.json`` leveling
rows (Malzahar voidling attacks, Azir soldier attacks, Illaoi tentacles)
plus the fight's own champion stats.  Values that exist only in wiki
prose — Annie's Tibbers pet attacks (the pets entry: 30/45/60 + 10% AP,
enrage then 0.625 AS cadence) and Malzahar's voidling attack speed
(0.665 + 2% growth) — are pinned against the module constants that
hardcode them, with the same citation in the module docstring.

Mechanics under test:

- Annie      Tibbers:   R burst + aura already modeled; the new
                        ``tibbers_attacks`` row prices Tibbers autos at
                        the pets-entry cadence over the fight window.
- Heimerdinger turrets: Q deploy prices turret shots + charged beam
                        (Evolution and R-upgraded Apex variants); Q is a
                        20s-recharge charge ability so one deploy per
                        window instead of a cast per second.
- Malzahar   voidlings: W is a zero-damage summon; ``voidling_attacks``
                        prices the swarm (2-4 active) at the sourced
                        per-attack formula and attack-speed cadence.
- Azir       Sand Soldiers: W soldier attacks replace autos (sourced
                        per-level + per-rank + AP row); Q's command dash
                        deals one instance per cast (in-game rule).
- Illaoi     tentacles: P prices commanded slams at the sourced
                        9-180 + 110% AD + 40% AP formula, scaled by the
                        Q rank increase.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import annie, malzahar

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_CACHE_KEY_BY_DISPLAY = {
    str(value.get("name", "")): key
    for key, value in _CHAMPION_DATA.items()
    if isinstance(value, dict) and str(value.get("name", "")).strip()
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fight(
    champion: str,
    *,
    options: dict | None = None,
    include_autos: bool = False,
    one_rotation: bool = False,
    auto_only: bool = False,
    duration: float = 10.0,
    target_health: float = 2000.0,
) -> dict:
    """One /api/calculate fight at level 18, rank 5 / R rank 3, no items."""
    mode = "one_rotation" if one_rotation else "time_based"
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": _FULL_RANKS,
        "fight_mode": "auto_only" if auto_only else mode,
        "fight_duration": duration,
        "include_auto_attacks": include_autos,
        "target_health": target_health,
        "target_armor": 0,
        "target_mr": 0,
    }
    if auto_only:
        payload["auto_attacks_only"] = True
    if options:
        payload["champion_options"] = options
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _leveling(champion: str, slot: str, attribute: str) -> dict:
    """Return the first leveling entry with this attribute, failing loudly."""
    ability = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


def _modifier_value(leveling: dict, modifier_index: int, rank: int) -> float:
    """Raw value of one modifier at rank (the E2/E3 test pattern)."""
    modifiers = leveling.get("modifiers", [])
    if modifier_index >= len(modifiers):
        return 0.0
    values = modifiers[modifier_index].get("values", [])
    if not values:
        return 0.0
    return float(values[min(max(rank, 1) - 1, len(values) - 1)])


def _resolve(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    stats: dict,
) -> float:
    """Sum one leveling entry at rank against the fight's own stats.

    Handles exactly the unit vocabularies the tested abilities use; an
    unexpected unit fails loudly so the test cannot silently pass with a
    dropped term.
    """
    total = 0.0
    for modifier in _leveling(champion, slot, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(max(rank, 1) - 1, len(values) - 1)
        value = float(values[idx])
        unit = (units[idx] if idx < len(units) else "").strip()
        if unit in ("", "%"):
            total += value
        elif unit == "% AP":
            total += value / 100.0 * float(stats.get("ability_power", 0.0))
        elif unit == "% AD":
            total += value / 100.0 * float(stats.get("attack_damage", 0.0))
        elif unit == "% bonus AD":
            total += value / 100.0 * float(stats.get("bonus_attack_damage", 0.0))
        else:
            raise AssertionError(
                f"unhandled unit {unit!r} for {champion} {slot} {attribute}"
            )
    return total


# ---------------------------------------------------------------------------
# Annie — Tibbers: burst + aura (existing) + auto attacks (E4-1)
# ---------------------------------------------------------------------------


class TestAnnieTibbers:
    """R prices burst + aura; the tibbers_attacks row prices Tibbers autos."""

    def test_tibbers_attacks_ten_second_window(self) -> None:
        """10s window -> 8 autos (5 enrage + 3 at 0.625 AS) x 60 magic = 480."""
        data = _fight("Annie")
        row = data["breakdown"]["tibbers_attacks"]
        assert row["count"] == 8
        assert row["damage_per_hit"] == pytest.approx(
            annie._TIBBERS_AUTO_BASE[2]
            + annie._TIBBERS_AUTO_AP_RATIO
            * float(data["champion_stats"].get("ability_power", 0.0))
        )
        assert row["total_damage"] == pytest.approx(row["damage_per_hit"] * 8)
        assert row["total_damage"] == pytest.approx(480.0)

    def test_r_burst_and_aura_unchanged(self) -> None:
        """R row stays burst (400) + 5s aura (4/tick x 20 ticks = 80)."""
        data = _fight("Annie")
        r_row = data["breakdown"]["R"]
        assert r_row["total_damage"] == pytest.approx(480.0)
        assert r_row["damage_per_hit"] is None  # aggregate cast row shape

    def test_tibbers_attacks_option_controls_count(self) -> None:
        """tibbers_attacks=3 -> 3 autos x 60 = 180 (player-steered uptime)."""
        data = _fight("Annie", options={"tibbers_attacks": 3})
        row = data["breakdown"]["tibbers_attacks"]
        assert row["count"] == 3
        assert row["total_damage"] == pytest.approx(180.0)

    def test_tibbers_attacks_zero_disables_row(self) -> None:
        data = _fight("Annie", options={"tibbers_attacks": 0})
        assert "tibbers_attacks" not in data["breakdown"]

    def test_one_rotation_prices_the_five_enrage_attacks(self) -> None:
        """One rotation (5s window): Tibbers lands his 5 enrage attacks."""
        data = _fight("Annie", one_rotation=True)
        row = data["breakdown"]["tibbers_attacks"]
        assert row["count"] == 5
        assert row["total_damage"] == pytest.approx(300.0)

    def test_autos_only_never_summons_tibbers(self) -> None:
        """R is what summons Tibbers, and autos-only casts nothing.

        Cached R text: "Active: Annie summons Tibbers to the target
        location..." — no Active, no pet, so the 480 magic this row used
        to price in an autos-only window came from a cast that never
        happened.  The explicit option cannot resurrect him either.
        """
        data = _fight("Annie", auto_only=True, include_autos=True)
        assert "tibbers_attacks" not in data["breakdown"]
        forced = _fight(
            "Annie", auto_only=True, include_autos=True, options={"tibbers_attacks": 5}
        )
        assert "tibbers_attacks" not in forced["breakdown"]


# ---------------------------------------------------------------------------
# Heimerdinger — turrets: Q deploy + R upgrade (Apex)
# ---------------------------------------------------------------------------


class TestHeimerdingerTurrets:
    """Q deploys a turret swarm priced once per 20s recharge."""

    def test_q_is_charge_ability_one_deploy_per_window(self) -> None:
        """Recharge 20s: one Q cast in a 10s fight (was 9 with the 1s
        inter-cast timer)."""
        data = _fight("Heimerdinger")
        assert data["breakdown"]["Q"]["casts"] == 1

    def test_evolution_turret_damage_sourced_values(self) -> None:
        """3 turrets x 3 shots x 23 (level 18) + 1 beam x 120 = 327 magic."""
        data = _fight("Heimerdinger")
        q_row = data["breakdown"]["Q"]
        assert q_row["total_damage"] == pytest.approx(327.0)
        # level-18 Evolution shot: 7 + (23-7)*17/17 = 23; beam rank 5: 120.
        shot = 7.0 + (23.0 - 7.0) * (18 - 1) / 17.0
        beam = 40.0 + 20.0 * (5 - 1)
        expected = (3 * 3 * shot) + beam
        assert q_row["total_damage"] == pytest.approx(expected)

    def test_apex_upgrade_variant(self) -> None:
        """q_variant=1 (R upgrade): Apex shots 120 x 9 + beam 180 = 1260."""
        data = _fight("Heimerdinger", options={"q_variant": 1})
        q_row = data["breakdown"]["Q"]
        assert q_row["total_damage"] == pytest.approx(1260.0)

    def test_turret_and_attack_options(self) -> None:
        """2 turrets x 2 shots, no beam: 4 x 23 = 92."""
        data = _fight(
            "Heimerdinger",
            options={"q_turrets": 2, "q_turret_attacks": 2, "q_beams": 0},
        )
        q_row = data["breakdown"]["Q"]
        assert q_row["casts"] == 1
        assert q_row["total_damage"] == pytest.approx(92.0)

    def test_one_rotation(self) -> None:
        data = _fight("Heimerdinger", one_rotation=True)
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(327.0)


# ---------------------------------------------------------------------------
# Malzahar — voidlings: W summon + sourced attack swarm
# ---------------------------------------------------------------------------


class TestMalzaharVoidlings:
    """W is a zero-damage summon; voidling_attacks prices the swarm."""

    def test_voidling_attack_formula(self) -> None:
        """Per attack: level 18 flat 64.5 + rank 5 base 20 (+0 bAD/AP) = 84.5."""
        data = _fight("Malzahar")
        stats = data["champion_stats"]
        leveling = _leveling("Malzahar", "W", "Magic Damage")
        expected = _modifier_value(leveling, 0, 18) + _modifier_value(leveling, 1, 5)
        expected += (
            _modifier_value(leveling, 2, 5)
            / 100.0
            * float(stats.get("bonus_attack_damage", 0.0))
        )
        expected += (
            _modifier_value(leveling, 3, 5)
            / 100.0
            * float(stats.get("ability_power", 0.0))
        )
        assert expected == pytest.approx(84.5)
        assert data["breakdown"]["voidling_attacks"]["damage_per_hit"] == (
            pytest.approx(expected)
        )

    def test_voidling_swarm_ten_second_window(self) -> None:
        """3 Voidlings in 10s: staggered summons (0.5/1.0/1.5s) at ~1.122s
        cadence -> 8 + 8 + 7 = 23 attacks x 84.5 = 1943.5 magic."""
        data = _fight("Malzahar")
        row = data["breakdown"]["voidling_attacks"]
        assert row["count"] == 23
        assert row["total_damage"] == pytest.approx(23 * 84.5)
        assert row["damage_per_hit"] == pytest.approx(84.5)

    def test_w_cast_row_is_zero_damage_summon(self) -> None:
        data = _fight("Malzahar")
        assert data["breakdown"]["W"]["total_damage"] == 0.0

    def test_voidling_count_option(self) -> None:
        """voidling_count=2: 8 + 8 = 16 attacks -> 1352 magic."""
        data = _fight("Malzahar", options={"voidling_count": 2})
        row = data["breakdown"]["voidling_attacks"]
        assert row["count"] == 16
        assert row["total_damage"] == pytest.approx(16 * 84.5)

    def test_voidling_attacks_option(self) -> None:
        """voidling_attacks=4 per voidling: 3 x 4 = 12 attacks -> 1014 magic."""
        data = _fight("Malzahar", options={"voidling_attacks": 4})
        row = data["breakdown"]["voidling_attacks"]
        assert row["count"] == 12
        assert row["total_damage"] == pytest.approx(1014.0)

    def test_one_rotation(self) -> None:
        """5s window: 4 + 3 + 3 = 10 attacks -> 845 magic."""
        data = _fight("Malzahar", one_rotation=True)
        row = data["breakdown"]["voidling_attacks"]
        assert row["count"] == 10
        assert row["total_damage"] == pytest.approx(845.0)

    def test_autos_only_summons_no_swarm(self) -> None:
        """W's Active is what summons Voidlings, and autos-only casts none.

        Cached W text: the Zz'Rot Swarm stacks come from "when he casts
        another ability" and "Active: Malzahar consumes all Zz'Rot Swarm
        stacks and, after a 0.5-second delay, summons a Voidling".  With
        no cast there is no swarm, so the 1943.5 magic this row used to
        price in an autos-only window was damage from a cast that never
        happened.  Neither swarm option can resurrect it.
        """
        data = _fight("Malzahar", auto_only=True, include_autos=True)
        assert "voidling_attacks" not in data["breakdown"]
        forced = _fight(
            "Malzahar",
            auto_only=True,
            include_autos=True,
            options={"voidling_count": 4, "voidling_attacks": 6},
        )
        assert "voidling_attacks" not in forced["breakdown"]

    def test_voidling_cadence_constant_matches_wiki(self) -> None:
        """The module's attack-speed constant reproduces the wiki formula:
        0.665*(1 + 2% growth) at level 18 -> 0.8911 AS (~1.122s)."""
        expected_as = 0.665 * (1 + 0.02 * 17 * (0.7025 + 0.0175 * 17))
        assert malzahar._voidling_attack_speed(18) == pytest.approx(expected_as)
        assert malzahar._voidling_attack_speed(18) == pytest.approx(0.8911, abs=1e-4)


# ---------------------------------------------------------------------------
# Azir — Sand Soldiers: W soldier autos + Q command dash
# ---------------------------------------------------------------------------


class TestAzirSandSoldiers:
    """W soldier attacks replace autos; Q's dash is one instance per cast."""

    def test_soldier_attack_value_sourced(self) -> None:
        """Per attack at level 18 / W rank 5: 72 + 110 + 65% AP = 182 magic."""
        data = _fight("Azir", include_autos=True)
        stats = data["champion_stats"]
        leveling = _leveling("Azir", "W", "Magic Damage")
        expected = _modifier_value(leveling, 0, 18) + _modifier_value(leveling, 1, 5)
        expected += (
            _modifier_value(leveling, 2, 5)
            / 100.0
            * float(stats.get("ability_power", 0.0))
        )
        assert expected == pytest.approx(182.0)
        auto = data["breakdown"]["auto_attacks"]
        # Magic vs physical is proven by mitigation in test_azir.py; here
        # the row is renamed (soldiers replace autos) and the per-hit value
        # matches the sourced W formula.
        assert auto["name"] == "Sand Soldier Attacks"
        assert auto["damage_per_hit"] == pytest.approx(expected)

    def test_soldier_attacks_ride_the_auto_stream(self) -> None:
        data = _fight("Azir", include_autos=True)
        auto = data["breakdown"]["auto_attacks"]
        assert auto["total_damage"] == pytest.approx(
            auto["damage_per_hit"] * auto["count"]
        )
        assert auto["count"] > 0

    def test_q_dash_damage_once_per_cast(self) -> None:
        """Q rank 5: 140 magic per cast (2 casts in 10s) = 280; soldier
        count must never multiply Q."""
        data = _fight("Azir", include_autos=True)
        stats = data["champion_stats"]
        q_expected = _resolve("Azir", "Q", "Magic Damage", 5, stats)
        assert q_expected == pytest.approx(140.0)
        q_row = data["breakdown"]["Q"]
        assert q_row["total_damage"] == pytest.approx(q_expected * q_row["casts"])
        assert q_row["casts"] == 2

    def test_soldier_count_scales_per_attack(self) -> None:
        """3 soldiers: 182 x 1.5 = 273 magic per attack (25% per extra)."""
        data = _fight("Azir", include_autos=True, options={"soldier_count": 3})
        auto = data["breakdown"]["auto_attacks"]
        assert auto["damage_per_hit"] == pytest.approx(182.0 * 1.5)

    def test_one_rotation_q_and_soldier_override(self) -> None:
        data = _fight("Azir", one_rotation=True)
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(140.0)
        assert data["breakdown"]["W"]["total_damage"] == 0.0
        assert (
            data["breakdown"]["W"]["detail"]
            == "Soldier attacks replace autos: 182 magic per attack"
        )


# ---------------------------------------------------------------------------
# Illaoi — tentacles: P spawn + commanded slam
# ---------------------------------------------------------------------------


class TestIllaoiTentacles:
    """P prices commanded tentacle slams at 9-180 + 110% AD + 40% AP."""

    def test_tentacle_slam_formula_sourced(self) -> None:
        """Level 18: 180 + 110% AD + 40% AP, x(1 + 30% Q rank increase)."""
        data = _fight("Illaoi")
        stats = data["champion_stats"]
        per_strike = _resolve("Illaoi", "P", "Bonus Physical Damage", 18, stats)
        q_increase = _modifier_value(_leveling("Illaoi", "Q", "Damage Increase"), 0, 5)
        expected = per_strike * (1.0 + q_increase / 100.0)
        row = data["breakdown"]["passive"]
        assert row["count"] == 1  # default p_tentacles
        assert row["damage_per_hit"] == pytest.approx(expected)
        assert row["total_damage"] == pytest.approx(expected)
        assert per_strike == pytest.approx(
            180.0 + 1.1 * float(stats.get("attack_damage", 0.0))
        )

    def test_tentacle_count_option(self) -> None:
        """p_tentacles=3 -> three commanded slams."""
        data = _fight("Illaoi", options={"p_tentacles": 3})
        row = data["breakdown"]["passive"]
        assert row["count"] == 3
        assert row["total_damage"] == pytest.approx(3 * row["damage_per_hit"])

    def test_q_commands_tentacles_not_direct_damage(self) -> None:
        """Q's active commands a tentacle; its damage lives on the P row."""
        data = _fight("Illaoi")
        assert data["breakdown"]["Q"]["total_damage"] == 0.0
        assert "represented by the explicit Tentacle proc count" in str(
            data["breakdown"]["Q"].get("detail", "")
        )

    def test_one_rotation(self) -> None:
        data = _fight("Illaoi", one_rotation=True)
        assert data["breakdown"]["passive"]["count"] == 1
        assert data["breakdown"]["passive"]["total_damage"] > 0
