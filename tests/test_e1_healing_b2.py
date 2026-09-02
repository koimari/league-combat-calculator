"""E1 heal-rule batch B2: sourced self-heals for eight champions.

Every amount below traces to ``data/champions.json`` leveling attributes
resolved at level 18 (ranks Q/W/E 5, R 3 unless level-derived) and, where a
ratio needs AP, "Rabadon's Deathcap" (130 flat AP + 30% Magical Opus = 169 AP
in this engine).

Hand-derived values (no items unless noted, AP = 0):
    Kayle W (Celestial Blessing)  rank 5: 155 (+ 25% AP)      -> 155; with DC 197.25
    Kha'Zix W (Void Spike)        rank 5: 135 (+ 50% AP)      -> 135; with DC 219.5
    Kindred R (Lamb's Respite)    rank 3: 375                 -> 375
    Lissandra R (Frozen Tomb)     rank 3: min 20 / max 40 per tick (+ 5.5% / 11% AP)
    Nidalee E (Primal Surge)      rank 5: min 150 / max 300 (+ 35% / 70% AP)
    Senna Q (Piercing Darkness)   rank 5: 120 (+ 40% bonus AD)(+ 35% AP) -> 132
                                   with default 40 Mist stacks (E3: +30 bonus AD); with DC 191.15
    Smolder R (MMOOOMMMM!)        rank 3: 170 (+ 50% bonus AD)(+ 75% AP) -> 170; with DC 296.75
    Sylas W (Kingslayer)          rank 5: min 100 / max 200 (+ 30% / 60% AP)

Missing-health heals ("0% : 100% (based on missing health)") interpolate
linearly from the minimum (full health) to the maximum (0 health); the tests
replay the public damage/heal ledger and assert each heal equals the formula
evaluated at the replayed live health.
"""

import pytest

from src import app as app_module
from src.calculator.champions.slotlib import extract_named
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stats import calculate_total_stats

_ENEMY_NAMES = ["Ahri", "Annie", "Orianna"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_ENEMY_RANKS = {"Q": 5, "W": 5, "E": 0, "R": 3}
_RABADONS = "Rabadon's Deathcap"


def _fight(
    champion: str,
    *,
    level: int = 18,
    ranks: dict | None = None,
    items: list[str] | None = None,
    enemies: int = 1,
) -> dict:
    payload = {
        "champion": champion,
        "level": level,
        "items": items or [],
        "role": "mid",
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "enemies": [
            {
                "champion": _ENEMY_NAMES[index % len(_ENEMY_NAMES)],
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": _ENEMY_RANKS,
            }
            for index in range(enemies)
        ],
    }
    if ranks is not None:
        payload["ability_ranks"] = ranks
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _main_heals(combat: dict) -> list[dict]:
    return [e for e in combat.get("healing_events", []) if e.get("attacker") == "main"]


def _sourced_flat(ability: dict, attribute: str, rank: int, stats: dict) -> float:
    """Resolve one sourced leveling value exactly as the engine does."""
    return float(extract_named(ability, attribute, rank, stats))


def _sourced_min_max(
    champion: str, slot: str, rank: int, items: list[str]
) -> tuple[float, float]:
    data = get_champion(champion)
    ability = data["abilities"][slot][0]
    stats = calculate_total_stats(
        data, 18, [get_item_by_name(i) for i in items], role="mid"
    )
    minimum = _sourced_flat(ability, "Minimum Heal", rank, stats)
    maximum = _sourced_flat(ability, "Maximum Heal", rank, stats)
    return minimum, maximum


def _sourced_min_max_per_tick(
    champion: str, slot: str, rank: int, items: list[str]
) -> tuple[float, float]:
    data = get_champion(champion)
    ability = data["abilities"][slot][0]
    stats = calculate_total_stats(
        data, 18, [get_item_by_name(i) for i in items], role="mid"
    )
    minimum = _sourced_flat(ability, "Minimum Heal per Tick", rank, stats)
    maximum = _sourced_flat(ability, "Maximum Heal per Tick", rank, stats)
    return minimum, maximum


def _expected_missing_health_heals(
    combat: dict, source: str, minimum: float, maximum: float
) -> list[tuple[float, float]]:
    """Replay the public ledger and predict every ``source`` heal amount.

    Damage rows apply post-mitigation damage to the main actor; heal rows
    apply their capped ``applied_amount``.  At the same timestamp damage is
    resolved before healing (the compiled action key orders damage at 0.0
    and healing at 1.0).  Returns (time, expected_raw_amount) pairs.
    """
    rows: list[tuple[float, int, object]] = []
    rows.extend(
        (float(event["time"]), 0, float(event["damage"]))
        for event in combat.get("events", [])
        if event.get("target") == "main" and float(event.get("damage", 0.0) or 0.0) > 0
    )
    rows.extend(
        (float(heal["time"]), 1, heal)
        for heal in combat.get("healing_events", [])
        if heal.get("attacker") == "main"
    )
    rows.sort(key=lambda row: (row[0], row[1]))

    main = next(
        participant
        for participant in combat["participants"]
        if participant["participant_id"] == "main"
    )
    max_health = float(main["survival"]["max_health"])
    health = max_health
    expected: list[tuple[float, float]] = []
    for time, kind, payload in rows:
        if kind == 0:
            health = max(0.0, health - float(payload))
            continue
        heal = payload
        applied = float(heal.get("applied_amount", heal.get("amount", 0.0)))
        if heal.get("source") == source:
            missing_ratio = (
                max(0.0, max_health - health) / max_health if max_health > 0 else 0.0
            )
            expected.append((time, minimum + (maximum - minimum) * missing_ratio))
        health = min(max_health, health + applied)
    return expected


def test_kayle_celestial_blessing_heals_flat_per_cast():
    """W heals a flat rank-scaled amount per cast (155 rank 5, +25% AP)."""
    combat = _fight("Kayle")
    heals = [e for e in _main_heals(combat) if e["source"] == "Celestial Blessing"]
    assert heals, "Celestial Blessing heal missing"
    assert all(e["amount"] == pytest.approx(155.0) for e in heals)
    # With Deathcap (169 AP): 155 + 25% AP = 197.25
    combat = _fight("Kayle", items=[_RABADONS])
    heals = [e for e in _main_heals(combat) if e["source"] == "Celestial Blessing"]
    assert heals
    data = get_champion("Kayle")
    stats = calculate_total_stats(data, 18, [get_item_by_name(_RABADONS)], role="mid")
    expected = _sourced_flat(data["abilities"]["W"][0], "Heal", 5, stats)
    assert expected == pytest.approx(197.25, abs=0.01)
    assert heals[0]["amount"] == pytest.approx(expected, abs=0.1)


def test_khazix_void_spike_heals_flat_per_cast():
    """W heals Kha'Zix inside the explosion (135 rank 5, +50% AP)."""
    combat = _fight("Khazix")
    heals = [e for e in _main_heals(combat) if e["source"] == "Void Spike"]
    assert heals, "Void Spike heal missing"
    assert all(e["amount"] == pytest.approx(135.0) for e in heals)
    # With Deathcap (169 AP): 135 + 50% AP = 219.5
    combat = _fight("Khazix", items=[_RABADONS])
    heals = [e for e in _main_heals(combat) if e["source"] == "Void Spike"]
    assert heals
    data = get_champion("Khazix")
    stats = calculate_total_stats(data, 18, [get_item_by_name(_RABADONS)], role="mid")
    expected = _sourced_flat(data["abilities"]["W"][0], "Heal", 5, stats)
    assert expected == pytest.approx(219.5, abs=0.01)
    assert all(e["amount"] == pytest.approx(expected, abs=0.1) for e in heals)


def test_kindred_lambs_respite_heals_when_blessing_ends():
    """R heals 375 (rank 3) when the 4-second blessing ends."""
    combat = _fight("Kindred")
    heals = [e for e in _main_heals(combat) if e["source"] == "Lamb's Respite"]
    assert heals, "Lamb's Respite heal missing"
    assert all(e["amount"] == pytest.approx(375.0) for e in heals)


def test_lissandra_frozen_tomb_heals_ticks_scaled_by_missing_health():
    """R self-cast heals 10 ticks of 0.25s, min 20 / max 40 per tick (rank 3)."""
    combat = _fight("Lissandra")
    ticks = [e for e in _main_heals(combat) if e["source"] == "Frozen Tomb"]
    assert len(ticks) == 10, "Frozen Tomb must heal 10 ticks per self-cast"
    minimum, maximum = _sourced_min_max_per_tick("Lissandra", "R", 3, [])
    assert (minimum, maximum) == (20.0, 40.0)
    for tick in ticks:
        assert minimum <= tick["raw_amount"] <= maximum
    expected = _expected_missing_health_heals(combat, "Frozen Tomb", minimum, maximum)
    assert len(expected) == 10
    for (_time, amount), tick in zip(expected, ticks, strict=False):
        assert tick["raw_amount"] == pytest.approx(amount, abs=0.1)


def test_nidalee_primal_surge_heals_scaled_by_missing_health():
    """E self-cast heals min 150 / max 300 (rank 5), scaled by missing health."""
    combat = _fight("Nidalee")
    heals = [e for e in _main_heals(combat) if e["source"] == "Primal Surge"]
    assert heals, "Primal Surge heal missing"
    minimum, maximum = _sourced_min_max("Nidalee", "E", 5, [])
    assert (minimum, maximum) == (150.0, 300.0)
    for heal in heals:
        assert minimum <= heal["raw_amount"] <= maximum
    expected = _expected_missing_health_heals(combat, "Primal Surge", minimum, maximum)
    assert len(expected) == len(heals)
    for (_time, amount), heal in zip(expected, heals, strict=False):
        assert heal["raw_amount"] == pytest.approx(amount, abs=0.1)


def test_senna_piercing_darkness_heals_flat_per_cast():
    """Q heals 120 (rank 5) + 35% AP; with Deathcap 179.15. The E3 Mist
    stack modeling (default 40 stacks = 30 bonus AD) feeds the heal's
    40% bonus-AD ratio: +12 without items, +12 on top of the Deathcap
    case."""
    combat = _fight("Senna")
    heals = [e for e in _main_heals(combat) if e["source"] == "Piercing Darkness"]
    assert heals, "Piercing Darkness heal missing"
    mist_bonus_ad = 0.75 * 40  # E3 default Mist stacks
    assert all(e["amount"] == pytest.approx(120.0 + 0.4 * mist_bonus_ad) for e in heals)
    combat = _fight("Senna", items=[_RABADONS])
    heals = [e for e in _main_heals(combat) if e["source"] == "Piercing Darkness"]
    assert heals
    data = get_champion("Senna")
    stats = calculate_total_stats(data, 18, [get_item_by_name(_RABADONS)], role="mid")
    expected = _sourced_flat(data["abilities"]["Q"][0], "Healing", 5, stats)
    assert expected == pytest.approx(179.15, abs=0.01)
    assert heals[0]["amount"] == pytest.approx(expected + 0.4 * mist_bonus_ad, abs=0.1)


def test_smolder_mmoooo_mm_heals_flat_per_cast():
    """R heals Smolder 170 (rank 3) + 75% AP; 296.75 with Deathcap."""
    combat = _fight("Smolder")
    heals = [e for e in _main_heals(combat) if e["source"] == "MMOOOMMMM!"]
    assert heals, "MMOOOMMMM! heal missing"
    assert all(e["amount"] == pytest.approx(170.0) for e in heals)
    combat = _fight("Smolder", items=[_RABADONS])
    heals = [e for e in _main_heals(combat) if e["source"] == "MMOOOMMMM!"]
    assert heals
    data = get_champion("Smolder")
    stats = calculate_total_stats(data, 18, [get_item_by_name(_RABADONS)], role="mid")
    expected = _sourced_flat(data["abilities"]["R"][0], "Self Heal", 3, stats)
    assert expected == pytest.approx(296.75, abs=0.01)
    assert heals[0]["amount"] == pytest.approx(expected, abs=0.1)


def test_sylas_kingslayer_heals_scaled_by_missing_health():
    """W heals Sylas only when it damages a champion (min 100 / max 200 rank 5)."""
    combat = _fight("Sylas")
    heals = [e for e in _main_heals(combat) if e["source"] == "Kingslayer"]
    assert heals, "Kingslayer heal missing"
    minimum, maximum = _sourced_min_max("Sylas", "W", 5, [])
    assert (minimum, maximum) == (100.0, 200.0)
    for heal in heals:
        assert minimum <= heal["raw_amount"] <= maximum
    expected = _expected_missing_health_heals(combat, "Kingslayer", minimum, maximum)
    assert len(expected) == len(heals)
    for (_time, amount), heal in zip(expected, heals, strict=False):
        assert heal["raw_amount"] == pytest.approx(amount, abs=0.1)


def test_lissandra_and_sylas_heals_stay_within_ap_scaled_bounds():
    """AP-scaling missing-health heals keep their sourced [min, max] bounds."""
    liss_min, liss_max = _sourced_min_max_per_tick("Lissandra", "R", 3, [_RABADONS])
    assert liss_min == pytest.approx(29.295, abs=0.01)
    assert liss_max == pytest.approx(58.59, abs=0.01)
    combat = _fight("Lissandra", items=[_RABADONS])
    ticks = [e for e in _main_heals(combat) if e["source"] == "Frozen Tomb"]
    assert len(ticks) == 10
    for tick in ticks:
        assert liss_min <= tick["raw_amount"] <= liss_max
    expected = _expected_missing_health_heals(combat, "Frozen Tomb", liss_min, liss_max)
    for (_time, amount), tick in zip(expected, ticks, strict=False):
        assert tick["raw_amount"] == pytest.approx(amount, abs=0.1)

    sylas_min, sylas_max = _sourced_min_max("Sylas", "W", 5, [_RABADONS])
    assert sylas_min == pytest.approx(150.7, abs=0.01)
    assert sylas_max == pytest.approx(301.4, abs=0.01)
    combat = _fight("Sylas", items=[_RABADONS])
    heals = [e for e in _main_heals(combat) if e["source"] == "Kingslayer"]
    assert heals
    for heal in heals:
        assert sylas_min <= heal["raw_amount"] <= sylas_max
    expected = _expected_missing_health_heals(
        combat, "Kingslayer", sylas_min, sylas_max
    )
    for (_time, amount), heal in zip(expected, heals, strict=False):
        assert heal["raw_amount"] == pytest.approx(amount, abs=0.1)
