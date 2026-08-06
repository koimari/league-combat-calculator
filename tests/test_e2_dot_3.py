"""E2-3: sourced DoT/channel tick counts (Skarner ... Zeri).

Each champion module / shared packet builder previously priced ONE tick of
a multi-tick ability.  The wiki cache carries BOTH the per-tick leveling
row and a "Total ..." row; this suite drives /api/calculate fights and
asserts the ability prices the full wiki Total (raw pre-mitigation damage)
with one event per sourced tick.

Expected totals are resolved from data/champions.json leveling rows via
``extract_named`` against the fight's own stat context (the participant
ledger the response returns), so every asserted number traces to the cache
— including stat-scaled rows (Zeri's % AD, Zaahen's % AD, Trundle's % of
the target's maximum health).

The response rounds event raw_damage and heal amounts to one decimal, so
per-tick sums may drift by a few tenths (e.g. Trundle 8 x 88.425 == 707.4
reported as 8 x 88.4 == 707.2); assertions use an absolute tolerance that
covers that rounding.

Worklist rows (data/worklists/e2-dot-ticks.json):
- Skarner Q: Bonus Physical Damage per Hit x 3 == Total Bonus Physical Damage
- Soraka Q: Heal per Tick x 12 == Total Heal (Starcall Rejuvenation)
- Teemo R: Magic Damage per Tick x 4 == Total Magic Damage
- Trundle R: Magic Damage Per Second x 8 == Total Magic Damage / Total Healing
- Udyr R: Magic Damage per Tick x 8 == Total Magic Damage
- Viktor R: Magic Damage (impact) + 6 x Magic Damage Per Tick == Total Magic Damage
- Vladimir W: Magic Damage Per Tick x 4 == Total Magic Damage
- Xayah Q: Physical Damage Per Hit x 2 == Total Physical Damage
- Yuumi R: Magic Damage per Hit + 4 x Reduced Damage per Hit == Total Magic Damage
- Zaahen Q: Physical Damage per Hit x 2 == Total Physical Damage
- Zac R: Magic Damage Per Hit + 3 x Reduced Damage Per Hit == Total Magic Damage
- Zeri Q: Physical Damage per Hit x 7 == Total Physical Damage

Deliberately not covered by this batch: the Udyr W (Iron Mantle) and Yuumi
R (Final Chapter) HEAL streams — those are authored by the E1-style
self-heal rule set (src/calculator/healing.py), which is outside this
task's file scope; the damage rows above are the E2 tick-count fixes.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions.slotlib import extract_named

_DATA = json.loads(
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("data", "champions.json")
    .read_text(encoding="utf-8")
)

_ENEMY = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
}

# One-decimal response rounding of per-event raw damage / heal amounts.
_ROUNDING_TOLERANCE = 0.6


def _fight(champion: str, ranks: dict | None = None) -> dict:
    """One-rotation /api/calculate fight, no items, level 18."""
    payload: dict = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "top",
        "fight_mode": "one_rotation",
        "include_auto_attacks": False,
        "champion_options": {},
        "enemies": [_ENEMY],
    }
    if ranks is not None:
        payload["ability_ranks"] = ranks
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


def _context(data: dict) -> tuple[dict, dict]:
    """(main stats, target stats) from the response participant ledger."""
    main = next(
        participant
        for participant in data["combat"]["participants"]
        if participant["participant_id"] == "main"
    )
    enemy = next(
        participant
        for participant in data["combat"]["participants"]
        if participant["participant_id"].startswith("enemy")
    )
    main_stats = main["stats"]
    max_health = float(enemy["survival"]["max_health"])
    target_stats = {
        "target_max_health": max_health,
        "target_current_health": max_health,
        "target_missing_health": 0.0,
    }
    return main_stats, target_stats


def _expected_total(
    champion: str,
    slot: str,
    attr: str,
    rank: int,
    main_stats: dict,
    target_stats: dict,
) -> float:
    """Resolve the wiki "Total ..." row at *rank* against the fight context."""
    ability = _DATA[champion]["abilities"][slot][0]
    return extract_named(ability, attr, rank, main_stats, target_stats)


def _assert_prices_full_total(data, source, expected, event_count, tolerance):
    events = _main_events(data, source)
    assert len(events) == event_count
    assert sum(float(event["raw_damage"]) for event in events) == pytest.approx(
        expected, abs=tolerance
    )


# ---------------------------------------------------------------------------
# Skarner — Shattered Earth (Q): 3 empowered attacks
# ---------------------------------------------------------------------------


class TestSkarnerShatteredEarth:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_q_prices_all_three_empowered_attacks(self):
        data = _fight("Skarner", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Skarner", "Q", "Total Bonus Physical Damage", 5, main_stats, target_stats
        )
        assert expected == pytest.approx(150.0)
        _assert_prices_full_total(
            data, "Q", expected, event_count=3, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Soraka — Starcall (Q): 12 Rejuvenation heal ticks
# ---------------------------------------------------------------------------


class TestSorakaStarcall:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_q_heal_prices_twelve_rejuvenation_ticks(self):
        """Heal per Tick x 12 == Total Heal (60/75/90/105/120)."""
        data = _fight("Soraka", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Soraka", "Q", "Total Heal", 5, main_stats, target_stats
        )
        assert expected == pytest.approx(120.0)
        heals = _main_heals(data, "Starcall · Rejuvenation")
        assert len(heals) == 12
        assert sum(float(heal["amount"]) for heal in heals) == pytest.approx(
            expected, abs=_ROUNDING_TOLERANCE
        )

    def test_q_damage_is_single_hit(self):
        """Starcall's magic damage is one hit (Magic Damage row)."""
        data = _fight("Soraka", self.RANKS)
        events = _main_events(data, "Q")
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Teemo — Noxious Trap (R): 4 poison ticks
# ---------------------------------------------------------------------------


class TestTeemoNoxiousTrap:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_r_prices_full_poison_total(self):
        """4 ticks of Magic Damage per Tick == Total Magic Damage (450)."""
        data = _fight("Teemo", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Teemo", "R", "Total Magic Damage", 3, main_stats, target_stats
        )
        assert expected == pytest.approx(450.0)
        _assert_prices_full_total(
            data, "R", expected, event_count=4, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Trundle — Subjugate (R): 8 half-second drain ticks
# ---------------------------------------------------------------------------


class TestTrundleSubjugate:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_r_prices_full_drain_total(self):
        """Magic Damage Per Second x 8 == Total Magic Damage (30% max HP)."""
        data = _fight("Trundle", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Trundle", "R", "Total Magic Damage", 3, main_stats, target_stats
        )
        assert expected == pytest.approx(0.30 * target_stats["target_max_health"])
        _assert_prices_full_total(
            data, "R", expected, event_count=8, tolerance=_ROUNDING_TOLERANCE
        )

    def test_r_heals_for_the_drain_total(self):
        """Subjugate heals for the same amount as the drain (Total Healing)."""
        data = _fight("Trundle", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Trundle", "R", "Total Healing", 3, main_stats, target_stats
        )
        heals = _main_heals(data, "Subjugate")
        assert len(heals) == 8
        assert sum(float(heal["amount"]) for heal in heals) == pytest.approx(
            expected, abs=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Udyr — Wingborne Storm (R): 8 blizzard ticks (level-derived ranks)
# ---------------------------------------------------------------------------


class TestUdyrWingborneStorm:
    def test_r_prices_full_blizzard_total(self):
        """8 ticks of Magic Damage per Tick == Total Magic Damage (rank 3: 208).

        Udyr rejects manual ability ranks; level 18's default skill order
        yields R rank 3 (taken at 6/11/16), matching the worklist's
        rank-3 per-tick value of 26.
        """
        data = _fight("Udyr", ranks=None)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Udyr", "R", "Total Magic Damage", 3, main_stats, target_stats
        )
        assert expected == pytest.approx(208.0)
        _assert_prices_full_total(
            data, "R", expected, event_count=8, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Viktor — Arcane Storm (R): impact + 6 storm bolts
# ---------------------------------------------------------------------------


class TestViktorArcaneStorm:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_r_prices_impact_plus_full_storm(self):
        """Magic Damage + 6 x Magic Damage Per Tick == Total Magic Damage (1120)."""
        data = _fight("Viktor", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Viktor", "R", "Total Magic Damage", 3, main_stats, target_stats
        )
        assert expected == pytest.approx(1120.0)
        # 1 impact event + 6 storm bolts (the worklist's 7.54 Total/PerTick
        # ratio counts the impact as 1.54 per-tick equivalents).
        _assert_prices_full_total(
            data, "R", expected, event_count=7, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Vladimir — Sanguine Pool (W): 4 pool ticks
# ---------------------------------------------------------------------------


class TestVladimirSanguinePool:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_w_prices_full_pool_total(self):
        """4 ticks of Magic Damage Per Tick == Total Magic Damage (300)."""
        data = _fight("Vladimir", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Vladimir", "W", "Total Magic Damage", 5, main_stats, target_stats
        )
        assert expected == pytest.approx(300.0)
        _assert_prices_full_total(
            data, "W", expected, event_count=4, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Xayah — Double Daggers (Q): 2 feathers
# ---------------------------------------------------------------------------


class TestXayahDoubleDaggers:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_q_prices_both_daggers(self):
        """2 x Physical Damage Per Hit == Total Physical Damage (210)."""
        data = _fight("Xayah", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Xayah", "Q", "Total Physical Damage", 5, main_stats, target_stats
        )
        assert expected == pytest.approx(210.0)
        _assert_prices_full_total(
            data, "Q", expected, event_count=2, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Yuumi — Final Chapter (R): 5 waves (1 full + 4 at 25%)
# ---------------------------------------------------------------------------


class TestYuumiFinalChapter:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_r_prices_all_five_waves(self):
        """Magic Damage per Hit + 4 x Reduced Damage per Hit == Total (350)."""
        data = _fight("Yuumi", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Yuumi", "R", "Total Magic Damage", 3, main_stats, target_stats
        )
        assert expected == pytest.approx(350.0)
        # 5 wave events; the worklist's 2.0 Total/PerHit ratio counts the
        # four reduced waves at 0.25 each (1 + 4 x 0.25 == 2.0).
        _assert_prices_full_total(
            data, "R", expected, event_count=5, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Zaahen — The Darkin Glaive (Q): 2 strikes
# ---------------------------------------------------------------------------


class TestZaahenDarkinGlaive:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_q_prices_both_strikes(self):
        """2 x Physical Damage per Hit == Total Physical Damage (75 + 100% AD)."""
        data = _fight("Zaahen", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Zaahen", "Q", "Total Physical Damage", 5, main_stats, target_stats
        )
        assert expected == pytest.approx(75.0 + main_stats["attack_damage"])
        _assert_prices_full_total(
            data, "Q", expected, event_count=2, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Zac — Let's Bounce! (R): initial + 3 reduced bounces
# ---------------------------------------------------------------------------


class TestZacLetsBounce:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_r_prices_all_bounces(self):
        """Magic Damage Per Hit + 3 x Reduced Damage Per Hit == Total (650)."""
        data = _fight("Zac", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Zac", "R", "Total Magic Damage", 3, main_stats, target_stats
        )
        assert expected == pytest.approx(650.0)
        # 4 bounce events; the worklist's 2.5 Total/PerHit ratio counts the
        # three reduced bounces at 0.5 each (1 + 3 x 0.5 == 2.5).
        _assert_prices_full_total(
            data, "R", expected, event_count=4, tolerance=_ROUNDING_TOLERANCE
        )


# ---------------------------------------------------------------------------
# Zeri — Burst Fire (Q): 7 rounds
# ---------------------------------------------------------------------------


class TestZeriBurstFire:
    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_q_prices_all_seven_rounds(self):
        """7 x Physical Damage per Hit == Total Physical Damage (38 + 110% AD)."""
        data = _fight("Zeri", self.RANKS)
        main_stats, target_stats = _context(data)
        expected = _expected_total(
            "Zeri", "Q", "Total Physical Damage", 5, main_stats, target_stats
        )
        assert expected == pytest.approx(38.0 + 1.10 * main_stats["attack_damage"])
        _assert_prices_full_total(
            data, "Q", expected, event_count=7, tolerance=_ROUNDING_TOLERANCE
        )
