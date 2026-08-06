"""E3 stack/charge/mark systems — batch 1 (12 champions).

One test per champion drives an ``/api/calculate`` fight at level 18
(basic abilities rank 5, ultimates rank 3, no items, target armor/MR 0 so
post-mitigation damage equals the raw wiki values) and asserts the
stack-based damage/empower row against values recomputed from
``data/champions.json`` leveling rows plus the fight's own champion stats
— every number traces to the wiki cache or the E3 worklist
(``data/worklists/e3-mechanics.json``). Values that exist only in wiki
prose (Twitch poison breakpoints, Brand's 2% burn, Braum's trigger
formula, Vel'Koz's 60% AP ratio) are pinned against the module constants
that hardcode them, with the same citation.

Mechanics under test:

- Varus    Blight:     3 stacks -> Q detonation (%maxHP magic per stack)
- Twitch   Deadly Venom: 6 stacks -> E Contaminate detonation + poison DoT
- Vel'Koz  Deconstruction: 3 stacks -> true-damage consume
- Tristana Explosive Charge: 4 stacks -> detonation
- Nasus    Siphoning Strike: permanent stacks scale Q
- Darius   Hemorrhage: 5 stacks -> R bonus + Noxian Might
- Brand    Blaze:      3 stacks -> detonation (%maxHP magic)
- Braum    Concussive Blows: 4 stacks -> trigger damage + stun
- Vayne    Silver Bolts: 3 hits -> true damage
- Kalista  Rend:       spears -> E detonation per stack
- Leona    Sunlight:   P detonation per mark
- Gnar     Hyper:      3 hits -> %maxHP magic proc
"""

import json
import re
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import braum, darius, twitch, varus

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
    duration: float = 10.0,
    target_health: float = 2000.0,
) -> dict:
    """One /api/calculate fight at level 18, rank 5 / R rank 3, no items."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": _FULL_RANKS,
        "fight_mode": "one_rotation" if one_rotation else "time_based",
        "fight_duration": duration,
        "include_auto_attacks": include_autos,
        "target_health": target_health,
        "target_armor": 0,
        "target_mr": 0,
    }
    if options:
        payload["champion_options"] = options
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _leveling(champion: str, slot: str, attribute: str, occurrence: int = 0) -> dict:
    """Return the N-th leveling entry with this attribute, failing loudly.

    Darius' passive stores several arrays under one "Per-Level Scaling"
    attribute (per-stack bleed, per-tick, five-stack, five-tick, and the
    Noxian Might row), so the Might row is occurrence 4.
    """
    ability = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    seen = 0
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                if seen == occurrence:
                    return leveling
                seen += 1
    raise AssertionError(
        f"{champion} {slot} has no leveling attribute {attribute!r} "
        f"(occurrence {occurrence})"
    )


def _modifier_value(leveling: dict, modifier_index: int, rank: int) -> float:
    """Raw value of one modifier at rank (the E2 test pattern)."""
    modifiers = leveling.get("modifiers", [])
    if modifier_index >= len(modifiers):
        return 0.0
    values = modifiers[modifier_index].get("values", [])
    if not values:
        return 0.0
    return float(values[min(max(rank, 1) - 1, len(values) - 1)])


def _normalize_unit(unit: str) -> str:
    unit = re.sub(r"\s+", " ", unit.strip())
    # The scraper sometimes inserts "the" / extra spaces ("%  of the
    # target's maximum health"); collapse to the canonical form.
    return re.sub(r"^% of the target's", "% of target's", unit)


def _resolve(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    stats: dict,
    target_max_health: float,
    *,
    stacks: float = 0.0,
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
        unit = _normalize_unit(units[idx]) if idx < len(units) else ""
        if unit in ("", "%"):
            total += value
        elif unit == "% AP":
            total += value / 100.0 * float(stats.get("ability_power", 0.0))
        elif unit == "% AD":
            total += value / 100.0 * float(stats.get("attack_damage", 0.0))
        elif unit == "% bonus AD":
            total += value / 100.0 * float(stats.get("bonus_attack_damage", 0.0))
        elif unit == "% of target's maximum health":
            total += value / 100.0 * target_max_health
        elif unit == "% per 100 AP":
            total += value * float(stats.get("ability_power", 0.0)) / 100.0
        elif unit == "% of Siphoning Strike stacks":
            total += value / 100.0 * stacks
        else:
            raise AssertionError(
                f"unhandled unit {unit!r} for {champion} {slot} {attribute}"
            )
    return total


def _attack_hits(data: dict) -> int:
    """Total attack applications: plain autos plus empowered-auto swings.

    Vayne's Tumble re-labels every swing onto the Q row, so the plain
    auto_attacks row can be empty while the on-hit still applies to all
    of the fight's attacks.
    """
    total = int(data["breakdown"].get("auto_attacks", {}).get("count", 0))
    for key, row in data["breakdown"].items():
        if key == "auto_attacks":
            continue
        if "basic attack" in str(row.get("detail", "")) and row.get("casts"):
            total += int(row["casts"])
    return total


# ---------------------------------------------------------------------------
# Varus — Blight: 3 stacks -> detonation on Q
# ---------------------------------------------------------------------------


class TestVarusBlight:
    """W applies Blight (max 3); abilities detonate all stacks."""

    def test_q_detonates_three_stacks(self) -> None:
        """Rank-5 W detonation: per stack 5% max HP + 1.3% per 100 AP.

        Level 18, no items (AP 0), target 2000 HP -> 3 x 100 = 300 magic,
        alongside the fully-charged arrow's 360 physical.
        """
        # P1-3: the W-active empowered-shot rider is disabled here so this
        # suite pins the detonation-only math (3 x per-stack %maxHP); the
        # empower is priced by tests/test_p1_review_3.py.
        data = _fight("Varus", include_autos=True, options={"w_active_empower": False})
        stats = data["champion_stats"]
        per_stack = _resolve(
            "Varus",
            "W",
            "Bonus Magic Damage per Stack",
            5,
            stats,
            data["target_effective_max_health"],
        )
        expected = per_stack * varus._BLIGHT_MAX_STACKS
        assert data["breakdown"]["blight_detonation"]["total_damage"] == pytest.approx(
            expected
        )
        assert data["breakdown"]["blight_detonation"]["count"] == 1
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            _resolve(
                "Varus",
                "Q",
                "Maximum Physical Damage",
                5,
                stats,
                data["target_effective_max_health"],
            )
        )

    def test_w_on_hit_rides_every_auto(self) -> None:
        """W's on-hit bonus magic damage applies per basic attack."""
        data = _fight("Varus", include_autos=True)
        stats = data["champion_stats"]
        per_hit = _resolve(
            "Varus",
            "W",
            "Bonus Magic Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["on_hit_ability_W"]
        assert row["total_damage"] == pytest.approx(per_hit * _attack_hits(data))
        assert row["damage_per_hit"] == pytest.approx(per_hit)

    def test_blight_stacks_option_seeds_the_detonation(self) -> None:
        """blight_stacks=0 models a fresh target: no detonation fires."""
        data = _fight(
            "Varus",
            options={"blight_stacks": 0, "w_active_empower": False},
            include_autos=True,
        )
        assert "blight_detonation" not in data["breakdown"]


# ---------------------------------------------------------------------------
# Twitch — Deadly Venom: stacks -> E Contaminate + poison DoT
# ---------------------------------------------------------------------------


class TestTwitchDeadlyVenom:
    """Autos apply poison (max 6); E detonates all stacks."""

    def test_e_prices_base_plus_per_stack_terms(self) -> None:
        """Rank-5 E: 60 base + 6 x (35 + 35% bonus AD) physical + 6 x 35% AP
        magic. The fight's R buff (+60 bonus AD at rank 3) is included in
        the response stats, exactly as in game."""
        data = _fight("Twitch")
        stats = data["champion_stats"]
        base = _resolve(
            "Twitch",
            "E",
            "Base Physical Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        per_stack = _resolve(
            "Twitch",
            "E",
            "Physical Damage Per Stack",
            5,
            stats,
            data["target_effective_max_health"],
        )
        casts = int(data["breakdown"]["E"]["casts"])
        expected_physical = base + per_stack * twitch._POISON_MAX_STACKS
        expected_magic = (
            twitch._E_MAGIC_AP_RATIO
            * float(stats.get("ability_power", 0.0))
            * twitch._POISON_MAX_STACKS
        )
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(
            casts * (expected_physical + expected_magic)
        )

    def test_poison_dot_prices_six_stacks_of_level_scaling(self) -> None:
        """Level 18 -> 30 (+18% AP) true damage per stack x 6 = 180."""
        data = _fight("Twitch")
        stats = data["champion_stats"]
        per_stack = 30.0 + twitch._POISON_AP_RATIO * float(
            stats.get("ability_power", 0.0)
        )
        row = data["breakdown"]["passive"]
        assert row["total_damage"] == pytest.approx(
            per_stack * twitch._POISON_MAX_STACKS
        )

    def test_poison_stacks_option_controls_the_detonation(self) -> None:
        """poison_stacks=0: E prices only its base (2 casts x 60), and the
        poison row is absent."""
        data = _fight("Twitch", options={"poison_stacks": 0})
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(120.0)
        assert "passive" not in data["breakdown"]


# ---------------------------------------------------------------------------
# Vel'Koz — Organic Deconstruction: 3 stacks -> true damage consume
# ---------------------------------------------------------------------------


class TestVelkozDeconstruction:
    """Abilities stack Deconstruction (max 3); the 3rd consumes for true
    damage."""

    def test_three_stack_consume_is_level_scaled_true_damage(self) -> None:
        """Level-18 array value 180 + 60% AP; no items -> 180 true damage."""
        data = _fight("Vel'Koz")
        stats = data["champion_stats"]
        flat = _modifier_value(_leveling("Vel'Koz", "P", "Per-Level Scaling"), 0, 18)
        expected = flat + 0.6 * float(stats.get("ability_power", 0.0))
        row = data["breakdown"]["passive"]
        assert row["total_damage"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Tristana — Explosive Charge: 4 stacks -> detonation
# ---------------------------------------------------------------------------


class TestTristanaExplosiveCharge:
    """E attaches; autos/abilities stack it (max 4, 100% increase)."""

    def test_four_stack_detonation_matches_full_stack_row(self) -> None:
        """Rank-5 E at 4 stacks: 160 + 4 x 40 = 320 physical (the wiki's
        Full Stack Physical Damage row); one cast in a 10s fight."""
        data = _fight("Tristana")
        stats = data["champion_stats"]
        base = _resolve(
            "Tristana",
            "E",
            "Minimum Physical Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        per_stack = _resolve(
            "Tristana",
            "E",
            "Bonus Damage Per Stack",
            5,
            stats,
            data["target_effective_max_health"],
        )
        expected = base + per_stack * 4
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(expected)
        assert data["breakdown"]["E"]["casts"] == 1

    def test_e_stacks_option_controls_the_charge(self) -> None:
        """e_stacks=0 prices the 0-stack base only."""
        data = _fight("Tristana", options={"e_stacks": 0})
        stats = data["champion_stats"]
        base = _resolve(
            "Tristana",
            "E",
            "Minimum Physical Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(base)


# ---------------------------------------------------------------------------
# Nasus — Siphoning Strike: permanent stacks scale Q
# ---------------------------------------------------------------------------


class TestNasusSiphoningStrike:
    """Every Q kill grants 3 permanent stacks (12 for champions); each
    stack adds 1 bonus damage to Q."""

    def test_q_scales_with_permanent_stacks(self) -> None:
        """q_stacks=100, one rotation: Q row = flat 120 + 100 stacks + the
        forced auto swing (empowers_next_auto), 1 cast."""
        data = _fight("Nasus", options={"q_stacks": 100}, one_rotation=True)
        stats = data["champion_stats"]
        flat = _resolve(
            "Nasus",
            "Q",
            "Bonus Physical Damage",
            5,
            stats,
            data["target_effective_max_health"],
            stacks=100.0,
        )
        assert flat == pytest.approx(220.0)
        row = data["breakdown"]["Q"]
        assert row["casts"] == 1
        assert row["total_damage"] == pytest.approx(
            220.0 + float(stats.get("attack_damage", 0.0))
        )

    def test_q_stacks_option_defaults_to_fresh_nasus(self) -> None:
        data = _fight("Nasus", one_rotation=True)
        stats = data["champion_stats"]
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            120.0 + float(stats.get("attack_damage", 0.0))
        )


# ---------------------------------------------------------------------------
# Darius — Hemorrhage: 5 stacks -> R bonus + Noxian Might
# ---------------------------------------------------------------------------


class TestDariusHemorrhage:
    """Damaging hits apply Hemorrhage (max 5); the 5th grants Noxian Might
    (+230 bonus AD at 18); R gains per-stack true damage."""

    def test_guillotine_scales_off_five_stacks_and_might(self) -> None:
        """Stacked opener (default): R rank 3 = 375 + 0.75 x 230 (base) +
        5 x (75 + 0.15 x 230) (per-stack) = 1095 true damage."""
        data = _fight("Darius")
        # The P bleed's level arrays and the Might array share the
        # "Per-Level Scaling" attribute; occurrence 4 is the Might row.
        might = _modifier_value(
            _leveling("Darius", "P", "Per-Level Scaling", occurrence=4), 0, 18
        )
        assert might == pytest.approx(230.0)
        base = _resolve("Darius", "R", "True Damage", 3, {}, 0.0) + 0.75 * might
        per_stack = (
            _resolve("Darius", "R", "Bonus Damage Per Stack", 3, {}, 0.0) + 0.15 * might
        )
        expected = base + per_stack * darius.P_BLEED_MAX_STACKS
        row = data["breakdown"]["R"]
        assert row["casts"] == 1
        assert row["total_damage"] == pytest.approx(expected)

    def test_unstacked_opener_loses_the_bonus(self) -> None:
        """starting_hemorrhage_stacks=0 opens on a fresh target: R lands
        with fewer stacks and no Noxian Might, so it strictly undercuts the
        stacked opener."""
        data = _fight("Darius", options={"starting_hemorrhage_stacks": 0})
        assert data["breakdown"]["R"]["total_damage"] < 1095.0


# ---------------------------------------------------------------------------
# Brand — Blaze: 3 stacks -> detonation
# ---------------------------------------------------------------------------


class TestBrandBlaze:
    """Abilities apply Ablaze (max 3); each burns 2% max HP over 4s; the
    3rd stack detonates for level-scaled %maxHP magic."""

    def test_blaze_prices_dot_plus_three_stack_detonation(self) -> None:
        """Level 18, 2000 HP: 3 x (2% x 2000 = 40) burn = 120 magic, plus
        the detonation = 12% x 2000 = 240 magic -> 360 total."""
        data = _fight("Brand", one_rotation=True)
        stats = data["champion_stats"]
        dot = 3 * (0.02 * data["target_effective_max_health"])
        detonation = (
            _modifier_value(_leveling("Brand", "P", "Max Health Damage"), 0, 18)
            / 100.0
            * data["target_effective_max_health"]
        )
        detonation += (
            _modifier_value(_leveling("Brand", "P", "Max Health Damage"), 1, 18)
            * float(stats.get("ability_power", 0.0))
            / 100.0
        )
        row = data["breakdown"]["passive"]
        assert row["total_damage"] == pytest.approx(dot + detonation)


# ---------------------------------------------------------------------------
# Braum — Concussive Blows: 4 stacks -> trigger damage
# ---------------------------------------------------------------------------


class TestBraumConcussiveBlows:
    """Autos and Q stack (max 4); the 4th procs 16 + 10 x level magic and
    opens an immunity window whose autos deal 40% of the trigger."""

    def test_fourth_stack_procs_trigger_damage(self) -> None:
        data = _fight("Braum", include_autos=True)
        trigger = braum._TRIGGER_BASE + braum._TRIGGER_PER_LEVEL * 18
        row = data["breakdown"]["passive"]
        match = re.search(
            r"(\d+) proc\(s\) \+ (\d+) empowered auto\(s\)", row["detail"]
        )
        assert match is not None, row["detail"]
        procs, empowered = int(match.group(1)), int(match.group(2))
        assert procs >= 1
        expected = procs * trigger + empowered * braum._BONUS_AUTO_RATIO * trigger
        assert row["total_damage"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Vayne — Silver Bolts: 3 hits -> true damage
# ---------------------------------------------------------------------------


class TestVayneSilverBolts:
    """Every 3rd hit on the same target procs 10% max-HP true damage
    (floored at the Minimum Bonus Damage row)."""

    def test_third_hit_procs_max_health_true_damage(self) -> None:
        data = _fight("Vayne", include_autos=True)
        stats = data["champion_stats"]
        proc = max(
            0.10 * data["target_effective_max_health"],
            _resolve(
                "Vayne",
                "W",
                "Minimum Bonus Damage",
                5,
                stats,
                data["target_effective_max_health"],
            ),
        )
        row = data["breakdown"]["on_hit_ability_W"]
        assert row["damage_per_hit"] == pytest.approx(proc)
        hits = _attack_hits(data)
        assert row["count"] == hits // 3
        # Smooth per-hit average including partial stacks (engine rule).
        assert row["total_damage"] == pytest.approx(proc / 3.0 * hits, abs=0.05)


# ---------------------------------------------------------------------------
# Kalista — Rend: spears -> E detonation per stack
# ---------------------------------------------------------------------------


class TestKalistaRend:
    """Autos lodge spears (up to 254); E rips them out for per-stack
    physical damage."""

    def test_rend_detonates_each_extra_spear(self) -> None:
        """10 spears, rank-5 E, one rotation: first 45 + 70% AD + 9 x
        (35 + 50% AD) physical (0 AP)."""
        data = _fight("Kalista", options={"rend_stacks": 10}, one_rotation=True)
        stats = data["champion_stats"]
        first = _resolve(
            "Kalista",
            "E",
            "Physical Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        additional = _resolve(
            "Kalista",
            "E",
            "Bonus Damage per Additional Stack",
            5,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["E"]
        assert row["casts"] == 1
        assert row["total_damage"] == pytest.approx(first + 9 * additional)


# ---------------------------------------------------------------------------
# Leona — Sunlight: P detonation per mark
# ---------------------------------------------------------------------------


class TestLeonaSunlight:
    """Abilities mark the target; damaging hits consume each mark for
    32-151 (by level) bonus magic damage."""

    def test_sunlight_detonation_is_level_scaled(self) -> None:
        data = _fight("Leona", one_rotation=True)
        level_value = _modifier_value(
            _leveling("Leona", "P", "Per-Level Scaling"), 0, 18
        )
        assert level_value == pytest.approx(151.0)
        row = data["breakdown"]["passive"]
        assert row["total_damage"] == pytest.approx(151.0)

    def test_p_marks_option_counts_the_detonations(self) -> None:
        data = _fight("Leona", options={"p_marks": 3}, one_rotation=True)
        assert data["breakdown"]["passive"]["total_damage"] == pytest.approx(3 * 151.0)


# ---------------------------------------------------------------------------
# Gnar — Hyper: 3 hits -> %maxHP magic proc
# ---------------------------------------------------------------------------


class TestGnarHyper:
    """Mini Gnar's W procs every 3rd hit: flat + %maxHP + AP magic."""

    def test_third_hit_procs_hyper(self) -> None:
        data = _fight("Gnar", include_autos=True)
        stats = data["champion_stats"]
        proc = _resolve(
            "Gnar",
            "W",
            "Bonus Magic Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["on_hit_ability_W"]
        assert row["damage_per_hit"] == pytest.approx(proc)
        hits = _attack_hits(data)
        assert row["count"] == hits // 3
        # The serialized row rounds to one decimal (smooth average).
        assert row["total_damage"] == pytest.approx(proc / 3.0 * hits, abs=0.05)
