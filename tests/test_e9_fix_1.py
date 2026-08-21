"""E9-1: final audit-gap fixes (Lucian, Miss Fortune, Morgana, Nunu & Willump,
Talon, Warwick, Teemo, Rumble).

Each champion drives /api/calculate fights at level 18 (basic abilities
rank 5, R rank 3, no items, target armor/MR 0) and asserts the corrected
sourced pricing recomputed from data/champions.json leveling rows against
the fight's own stats — the same conventions as test_e2_dot_3.py and
test_e3_stacks_1.py.

Fixes under test:

- Lucian   R: 22 x "Physical Damage Per Shot" (full 3s channel, was 1 shot)
           P: Lightslinger second shot (60% AD at level 18) per auto
- Miss Fortune R: "Physical Damage per Wave" x "Total Waves" (18 at R3)
- Morgana  W: 10 x "Maximum Damage Per Tick" (was 1 tick)
           R: 2 x "Magic Damage" (initial + 3s tether-break hit)
           P: Soul Siphon heals 18% of post-mitigation ability damage
- Nunu     Q: "Champion Magic Damage" (was Non-Champion True Damage)
           Q heal: "Base Champion Heal" at full health
- Talon    P: 3-stack consume bleed (16 per-tick hits == per-level total)
           Q heal: per-level on-kill flat heal
- Warwick  R: "Total Magic Damage" (was no_damage) + 100% R self-heal
- Teemo    E: on-hit + 4 poison ticks ("Magic Damage per Tick" x4 ==
           "Total Poison Damage")
- Rumble   R: 20 Burning ticks ("Magic Damage per Tick" x20 ==
           "Maximum Magic Damage")
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import lucian, slotlib

_DATA = json.loads(
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("data", "champions.json")
    .read_text(encoding="utf-8")
)
_CACHE_KEY_BY_DISPLAY = {
    str(value.get("name", "")): key
    for key, value in _DATA.items()
    if isinstance(value, dict) and str(value.get("name", "")).strip()
}

_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_ENEMY = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    # Keep this numeric regression fixture free of incoming Ahri Charm
    # downtime. Control timing has dedicated interaction tests.
    "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
}

# One-decimal response rounding of per-event raw damage / heal amounts.
_ROUNDING_TOLERANCE = 0.6


def _fight(
    champion: str,
    *,
    autos: bool = False,
    enemies: bool = True,
    options: dict | None = None,
    mode: str = "one_rotation",
    duration: float = 10.0,
) -> dict:
    """One /api/calculate fight: level 18, rank 5 / R rank 3, no items."""
    payload: dict = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": _FULL_RANKS,
        "fight_mode": mode,
        "fight_duration": duration,
        "include_auto_attacks": autos,
        "target_health": 2000.0,
        "target_armor": 0,
        "target_mr": 0,
    }
    if mode == "auto_only":
        payload["auto_attacks_only"] = True
    if options:
        payload["champion_options"] = options
    if enemies:
        payload["enemies"] = [_ENEMY]
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _main_events(data: dict, source: str) -> list[dict]:
    return [
        event
        for event in data["combat"]["events"]
        if event.get("attacker") == "main" and event.get("source") == source
    ]


def _main_heals(data: dict, source: str) -> list[dict]:
    return [
        heal
        for heal in data["combat"]["healing_events"]
        if heal.get("attacker") == "main" and heal.get("source") == source
    ]


def _stats(data: dict) -> dict:
    """The main fight's own stats (participant ledger, enemy fight)."""
    main = next(
        participant
        for participant in data["combat"]["participants"]
        if participant["participant_id"] == "main"
    )
    return main["stats"]


def _resolve(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    stats: dict,
    target_max_health: float,
) -> float:
    """Resolve one leveling row against the fight's own stat context."""
    ability = _DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    return slotlib.extract_named(
        ability,
        attribute,
        rank,
        stats,
        {"target_max_health": target_max_health},
    )


def _assert_prices_full_total(data, source, expected, event_count, tolerance):
    events = _main_events(data, source)
    assert len(events) == event_count
    assert sum(float(event["raw_damage"]) for event in events) == pytest.approx(
        expected, abs=tolerance
    )


# ---------------------------------------------------------------------------
# Lucian — R full 3s channel (22 shots) + P Lightslinger double-shot
# ---------------------------------------------------------------------------


class TestLucian:
    def test_r_prices_all_twenty_two_channel_shots(self):
        """Per-shot x22 == the full 3-second channel (rank 3: 1551)."""
        data = _fight("Lucian", enemies=False)
        stats = data["champion_stats"]
        per_shot = _resolve("Lucian", "R", "Physical Damage Per Shot", 3, stats, 2000.0)
        assert per_shot == pytest.approx(70.5)
        expected = per_shot * 22
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Lucian")
        _assert_prices_full_total(
            events_data, "R", expected, event_count=22, tolerance=0.6
        )

    def test_p_lightslinger_second_shot_per_auto(self):
        """Double-shot: 60% AD at level 18, one per basic attack."""
        data = _fight("Lucian", autos=True, mode="time_based", enemies=False)
        stats = data["champion_stats"]
        ad = float(stats["attack_damage"])
        ratio = lucian._lightslinger_ratio(18)
        assert ratio == pytest.approx(0.60)
        autos = int(data["breakdown"]["auto_attacks"]["count"])
        row = data["breakdown"]["double_shot"]
        assert row["total_damage"] == pytest.approx(ratio * ad * autos, abs=0.6)


# ---------------------------------------------------------------------------
# Miss Fortune — Bullet Time full channel (per-wave x Total Waves)
# ---------------------------------------------------------------------------


class TestMissFortune:
    def test_r_prices_all_sourced_waves(self):
        """Per-wave x18 == the full channel at rank 3 (1756.8)."""
        data = _fight("Miss Fortune", enemies=False)
        stats = data["champion_stats"]
        per_wave = _resolve(
            "Miss Fortune", "R", "Physical Damage per Wave", 3, stats, 2000.0
        )
        waves = int(
            slotlib.extract_value(
                _DATA[_CACHE_KEY_BY_DISPLAY["Miss Fortune"]]["abilities"]["R"][0],
                "Total Waves",
                3,
            )
        )
        assert waves == 18
        expected = per_wave * waves
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Miss Fortune")
        _assert_prices_full_total(
            events_data, "R", expected, event_count=18, tolerance=0.6
        )


# ---------------------------------------------------------------------------
# Morgana — W 10 ticks, R tether-break second hit, P Soul Siphon heal
# ---------------------------------------------------------------------------


class TestMorgana:
    def test_w_prices_all_ten_storm_ticks(self):
        """Maximum Damage Per Tick x10 == Maximum Total Damage (700)."""
        data = _fight("Morgana", enemies=False)
        stats = data["champion_stats"]
        expected = _resolve("Morgana", "W", "Maximum Total Damage", 5, stats, 2000.0)
        assert expected == pytest.approx(700.0)
        assert data["breakdown"]["W"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Morgana")
        _assert_prices_full_total(
            events_data, "W", expected, event_count=10, tolerance=0.6
        )

    def test_r_prices_initial_plus_tether_break_hit(self):
        """Magic Damage x2 == Total Magic Damage (700)."""
        data = _fight("Morgana", enemies=False)
        stats = data["champion_stats"]
        expected = _resolve("Morgana", "R", "Total Magic Damage", 3, stats, 2000.0)
        assert expected == pytest.approx(700.0)
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Morgana")
        _assert_prices_full_total(
            events_data, "R", expected, event_count=2, tolerance=0.6
        )

    def test_p_soul_siphon_heals_18_percent_of_ability_damage(self):
        """18% of the post-mitigation ability (Q/W/R) damage dealt."""
        data = _fight("Morgana")
        heals = _main_heals(data, "Soul Siphon")
        assert heals
        ability_damage = sum(
            float(event["damage"])
            for event in data["combat"]["events"]
            if event.get("attacker") == "main"
            and event.get("source") in {"Q", "W", "R"}
        )
        assert sum(float(h["raw_amount"]) for h in heals) == pytest.approx(
            0.18 * ability_damage, abs=0.6
        )


# ---------------------------------------------------------------------------
# Nunu & Willump — Q champion damage basis + Q champion heal
# ---------------------------------------------------------------------------


class TestNunu:
    def test_q_prices_champion_magic_damage(self):
        """Champion Magic Damage 220 at rank 5 (was 1200 true minion row)."""
        data = _fight("Nunu & Willump", enemies=False)
        stats = data["champion_stats"]
        expected = _resolve(
            "Nunu & Willump", "Q", "Champion Magic Damage", 5, stats, 2000.0
        )
        assert expected == pytest.approx(220.0)
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Nunu & Willump")
        events = _main_events(events_data, "Q")
        assert len(events) == 1
        assert float(events[0]["raw_damage"]) == pytest.approx(expected, abs=0.6)

    def test_q_heals_base_champion_heal_at_full_health(self):
        """Base Champion Heal 111 at rank 5, full health (no empowerment)."""
        data = _fight("Nunu & Willump")
        heals = _main_heals(data, "Consume")
        assert len(heals) == 1
        assert heals[0]["raw_amount"] == pytest.approx(111.0, abs=0.6)


# ---------------------------------------------------------------------------
# Talon — P 3-stack consume bleed + Q on-kill heal
# ---------------------------------------------------------------------------


class TestTalon:
    def test_p_prices_the_three_stack_consume_bleed(self):
        """Per-tick x16 == the per-level total bleed (280 at level 18)."""
        data = _fight("Talon", enemies=False)
        stats = data["champion_stats"]
        expected = _resolve("Talon", "P", "Per-Level Scaling", 18, stats, 2000.0)
        assert expected == pytest.approx(280.0)
        row = data["breakdown"]["passive"]
        assert row["total_damage"] == pytest.approx(expected, abs=0.6)
        assert row["count"] == 1

    def test_autos_only_never_stacks_wound_so_no_bleed(self):
        """Abilities apply Wound; a basic attack only consumes it.

        Cached P text: "Talon's abilities apply a stack of Wound to
        enemy champions and large monsters hit for 6 seconds, refreshing
        on basic attacks... Talon's next basic attack on-hit against an
        enemy with 3 Wound stacks is empowered to consume them all."
        The consumer is a swing but the stacks are not, so an autos-only
        window has nothing to consume — the explicit proc count cannot
        conjure one either.
        """
        data = _fight("Talon", enemies=False, mode="auto_only", autos=True)
        assert "passive" not in data["breakdown"]
        forced = _fight(
            "Talon",
            enemies=False,
            mode="auto_only",
            autos=True,
            options={"passive_procs": 3},
        )
        assert "passive" not in forced["breakdown"]

    def test_q_heals_the_sourced_per_level_amount(self):
        """On-kill flat heal: 55 at level 18 (per-level array)."""
        data = _fight("Talon")
        heals = _main_heals(data, "Noxian Diplomacy")
        assert len(heals) == 1
        assert heals[0]["raw_amount"] == pytest.approx(55.0, abs=0.6)


# ---------------------------------------------------------------------------
# Warwick — R Total Magic Damage + the 100% R self-heal it unlocks
# ---------------------------------------------------------------------------


class TestWarwick:
    def test_r_prices_total_magic_damage(self):
        """Total Magic Damage 525 at rank 3 (was no_damage)."""
        data = _fight("Warwick", enemies=False)
        stats = data["champion_stats"]
        expected = _resolve("Warwick", "R", "Total Magic Damage", 3, stats, 2000.0)
        assert expected == pytest.approx(525.0)
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Warwick")
        _assert_prices_full_total(
            events_data, "R", expected, event_count=1, tolerance=0.6
        )

    def test_r_heals_for_all_its_post_mitigation_damage(self):
        """Infinite Duress heals 100% of the R damage it deals."""
        data = _fight("Warwick")
        heals = _main_heals(data, "Infinite Duress")
        assert len(heals) == 1
        r_events = _main_events(data, "R")
        assert float(heals[0]["raw_amount"]) == pytest.approx(
            float(r_events[0]["damage"]), abs=0.6
        )


# ---------------------------------------------------------------------------
# Teemo — E on-hit + the full poison DoT
# ---------------------------------------------------------------------------


class TestTeemo:
    def test_e_prices_on_hit_plus_full_poison_do_t(self):
        """On-hit + 4 x Magic Damage per Tick == on-hit + Total Poison."""
        data = _fight("Teemo", enemies=False)
        stats = data["champion_stats"]
        on_hit = _resolve("Teemo", "E", "Magic Damage On-Hit", 5, stats, 2000.0)
        poison_total = _resolve("Teemo", "E", "Total Poison Damage", 5, stats, 2000.0)
        assert on_hit == pytest.approx(65.0)
        assert poison_total == pytest.approx(120.0)
        expected = on_hit + poison_total
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Teemo")
        events = _main_events(events_data, "E")
        assert len(events) == 5  # on-hit + 4 poison ticks
        assert sum(float(event["raw_damage"]) for event in events) == pytest.approx(
            expected, abs=0.6
        )


# ---------------------------------------------------------------------------
# Rumble — R full Burning DoT (20 ticks)
# ---------------------------------------------------------------------------


class TestRumble:
    def test_r_prices_all_twenty_burning_ticks(self):
        """Magic Damage per Tick x20 == Maximum Magic Damage (1400)."""
        data = _fight("Rumble", enemies=False)
        stats = data["champion_stats"]
        expected = _resolve("Rumble", "R", "Maximum Magic Damage", 3, stats, 2000.0)
        assert expected == pytest.approx(1400.0)
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(expected)
        events_data = _fight("Rumble")
        _assert_prices_full_total(
            events_data, "R", expected, event_count=20, tolerance=0.6
        )
