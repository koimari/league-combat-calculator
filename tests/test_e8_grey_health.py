"""E8a: the grey-health primitive — Pyke, Rengar, Tahm Kench, Mordekaiser.

Grey-health champions store a sourced percentage of post-mitigation
damage TAKEN as a grey pool and pay it back as a heal when their active
consumes it.  The 1v1 heal derivation only sees the main's OUTGOING
events, so participant_timeline.py authors the receipts against its
incoming ledger (enemy -> main pair packets).  Every asserted ratio
traces to data/champions.json:

- Pyke P (prose): stores 9% (+ 0.2% per 1 Lethality) of post-mitigation
  damage taken, 40% (+ 0.4% per 1 Lethality) with 2+ visible enemies,
  capped at 80 (+ 800% bonus AD) and 55% of maximum health; the
  out-of-vision consume heals 100% of the pool and is a vision boundary
  (no in-window heal is authored).
- Rengar W (prose): stores 50% of post-mitigation damage taken in the
  last 1.5 seconds; the active heals the stored pool (the leveling rows
  carry only the ability's magic damage, not a heal amount).
- Tahm Kench E (leveling): "Damage Stored into Grey Health"
  15/23/31/39/47% by E rank (42/44/46/48/50% with 2+ visible enemies);
  the out-of-combat consume (4 s without damage) restores
  "Max Health Damage" 60% : 100% (based on level) of the pool.
- Mordekaiser W (prose + leveling): stores 45% of post-mitigation
  damage dealt and 7.5% of pre-mitigation damage taken, capped at 30%
  of maximum health; the recast (modeled at W cast + 0.5 s) heals
  "Shield to Healing" 35/37.5/40/42.5/45% by W rank of the stored
  shield.
- Kled P (Skaarl): the mounted duo's damage pool is a revive-boundary
  pattern (like Aatrox's ghost atom) and is documented in the module,
  not authored as a heal.
"""

import pytest

from src import app as app_module

_ENEMY_NAMES = ["Ahri", "Annie"]


def _fight(
    champion: str,
    *,
    level: int = 18,
    duration: int = 10,
    auto: bool = True,
    ranks: dict | None = None,
    enemy_ranks: dict | None = None,
    items: list[str] | None = None,
    enemy_count: int = 1,
) -> dict:
    """Run one /api/calculate time-based fight and return the combat ledger."""
    payload = {
        "champion": champion,
        "level": level,
        "items": items or [],
        "role": "top",
        **({"ability_ranks": ranks} if ranks is not None else {}),
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": auto,
        "enemies": [
            {
                "champion": _ENEMY_NAMES[index % len(_ENEMY_NAMES)],
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": enemy_ranks or {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
            for index in range(enemy_count)
        ],
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _incoming(combat: dict) -> list[dict]:
    return [e for e in combat["events"] if e.get("target") == "main"]


def _outgoing(combat: dict) -> list[dict]:
    return [e for e in combat["events"] if e.get("attacker") == "main"]


def _main_survival(combat: dict) -> dict:
    return next(p for p in combat["participants"] if p["participant_id"] == "main")[
        "survival"
    ]


def _main_stats(combat: dict) -> dict:
    return next(p for p in combat["participants"] if p["participant_id"] == "main")[
        "stats"
    ]


# ---------------------------------------------------------------------------
# Rengar W — 50% of the last 1.5 s of post-mitigation damage, healed on cast
# ---------------------------------------------------------------------------


def test_rengar_w_stores_half_of_recent_damage_and_heals_on_cast():
    # 16 s: Rengar's rank-5 W casts at t=0 and t=10; the t=10 cast consumes
    # the pool built from damage taken in [8.5, 10].
    combat = _fight("Rengar", duration=16, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    incoming = _incoming(combat)
    window = [e for e in incoming if 8.5 <= e["time"] <= 10.0]
    assert window, "expected incoming damage inside the 1.5 s window"
    for event in window:
        assert event["grey_health_stored"] == pytest.approx(
            0.5 * event["damage"], rel=0.01
        )
    heals = [
        h
        for h in combat["healing_events"]
        if h["source"] == "Battle Roar (grey health)"
        and h["time"] == pytest.approx(10.0)
    ]
    assert heals, "Rengar W grey-health heal at the t=10 cast missing"
    expected = 0.5 * sum(e["damage"] for e in window)
    assert heals[0]["raw_amount"] == pytest.approx(expected, rel=0.01)
    assert heals[0]["applied_amount"] > 0.0
    assert heals[0]["grey_health"] is True
    survival = _main_survival(combat)
    # Consumed = every W-cast heal: the t=0 cast heals the opening burst
    # (same-timestamp, damage-before-heal order) and the t=10 cast heals
    # the 1.5 s window.
    all_heals = [
        h
        for h in combat["healing_events"]
        if h["source"] == "Battle Roar (grey health)"
    ]
    assert survival["grey_health_consumed"] == pytest.approx(
        sum(h["raw_amount"] for h in all_heals), rel=0.01
    )
    assert survival["grey_health_stored"] == pytest.approx(
        0.5 * sum(e["damage"] for e in incoming), rel=0.01
    )


def test_rengar_w_first_cast_heals_same_timestamp_burst():
    # The ledger resolves damage before heals at one timestamp, so the
    # t=0 W heals the pool from the enemy's opening burst (window
    # [-1.5, 0] is inclusive of the cast instant — documented boundary).
    combat = _fight("Rengar", duration=10, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    incoming = _incoming(combat)
    burst = [e for e in incoming if e["time"] == 0.0]
    heals = [
        h
        for h in combat["healing_events"]
        if h["source"] == "Battle Roar (grey health)" and h["time"] == 0.0
    ]
    assert heals, "Rengar W grey-health heal at the t=0 cast missing"
    assert heals[0]["raw_amount"] == pytest.approx(
        0.5 * sum(e["damage"] for e in burst), rel=0.01
    )


# ---------------------------------------------------------------------------
# Tahm Kench E — rank % stored, level-scaled restore after 4 s out of combat
# ---------------------------------------------------------------------------


def test_tahm_kench_e_stores_rank_percent_and_restores_out_of_combat():
    # auto off + Q-only enemy: Ahri's Q lands at t=0 and t=7.25, then
    # nothing — the 4 s out-of-combat window opens at 11.25 (duration 12).
    combat = _fight(
        "TahmKench",
        duration=12,
        auto=False,
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        enemy_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
    )
    incoming = _incoming(combat)
    assert incoming
    for event in incoming:
        assert event["grey_health_stored"] == pytest.approx(
            0.47 * event["damage"], rel=0.01
        )
    pool = 0.47 * sum(e["damage"] for e in incoming)
    survival = _main_survival(combat)
    assert survival["grey_health_stored"] == pytest.approx(pool, abs=0.2)
    last_damage = max(e["time"] for e in incoming)
    heals = [
        h for h in combat["healing_events"] if h["source"] == "Thick Skin (grey health)"
    ]
    assert heals, "Tahm Kench out-of-combat grey restore missing"
    assert heals[0]["time"] == pytest.approx(last_damage + 4.0)
    # Level 18 restore = 100% of the pool ("Max Health Damage" row 100).
    assert heals[0]["raw_amount"] == pytest.approx(pool, abs=0.2)
    assert survival["grey_health_consumed"] == pytest.approx(pool, abs=0.2)


def test_tahm_kench_e_restore_scales_with_level():
    combat = _fight(
        "TahmKench",
        level=11,
        duration=12,
        auto=False,
        ranks={"Q": 4, "W": 2, "E": 4, "R": 1},
        enemy_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
    )
    incoming = _incoming(combat)
    # E rank 4 -> "Damage Stored into Grey Health" row 39%.
    pool = 0.39 * sum(e["damage"] for e in incoming)
    heals = [
        h for h in combat["healing_events"] if h["source"] == "Thick Skin (grey health)"
    ]
    assert heals, "Tahm Kench out-of-combat grey restore missing"
    # Level 11 restore row = 83.53% (index 10 of the 18-entry level row).
    assert heals[0]["raw_amount"] == pytest.approx(0.8353 * pool, abs=0.2)


# ---------------------------------------------------------------------------
# Mordekaiser W — 45% dealt + 7.5% pre-mitigation taken, recast heal by rank
# ---------------------------------------------------------------------------


def test_mordekaiser_w_stores_dealt_and_taken_and_heals_on_recast():
    combat = _fight("Mordekaiser", auto=False, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    incoming = _incoming(combat)
    for event in incoming:
        assert event["grey_health_stored"] == pytest.approx(
            0.075 * event["raw_damage"], rel=0.01
        )
    outgoing = [e for e in _outgoing(combat) if e.get("damage", 0) > 0]
    for event in outgoing:
        assert event["grey_health_stored"] == pytest.approx(
            0.45 * event["damage"], rel=0.01
        )
    taken_pre = sum(e["raw_damage"] for e in incoming if e["time"] <= 0.5)
    dealt = sum(e["damage"] for e in outgoing if e["time"] <= 0.5)
    max_health = float(_main_stats(combat)["health"])
    pool = min(0.30 * max_health, 0.45 * dealt + 0.075 * taken_pre)
    heals = [
        h
        for h in combat["healing_events"]
        if h["source"] == "Indestructible (grey health)"
    ]
    assert heals, "Mordekaiser W recast heal missing"
    # W casts at t=0.5; the recast is modeled at +0.5 s (earliest
    # available per the wiki prose).
    assert heals[0]["time"] == pytest.approx(1.0)
    assert heals[0]["raw_amount"] == pytest.approx(0.45 * pool, abs=0.2)
    survival = _main_survival(combat)
    assert survival["grey_health_consumed"] == pytest.approx(0.45 * pool, abs=0.2)


def test_mordekaiser_w_recast_heal_scales_with_w_rank():
    combat = _fight("Mordekaiser", auto=False, ranks={"Q": 5, "W": 1, "E": 5, "R": 3})
    incoming = _incoming(combat)
    outgoing = [e for e in _outgoing(combat) if e.get("damage", 0) > 0]
    taken_pre = sum(e["raw_damage"] for e in incoming if e["time"] <= 0.5)
    dealt = sum(e["damage"] for e in outgoing if e["time"] <= 0.5)
    max_health = float(_main_stats(combat)["health"])
    pool = min(0.30 * max_health, 0.45 * dealt + 0.075 * taken_pre)
    heals = [
        h
        for h in combat["healing_events"]
        if h["source"] == "Indestructible (grey health)"
    ]
    assert heals, "Mordekaiser W recast heal missing"
    # W rank 1 -> "Shield to Healing" row 35%.
    assert heals[0]["raw_amount"] == pytest.approx(0.35 * pool, abs=0.2)


# ---------------------------------------------------------------------------
# Pyke P — 9% (+0.2%/Lethality) stored, out-of-vision consume is a boundary
# ---------------------------------------------------------------------------


def test_pyke_p_stores_nine_percent_and_authors_no_in_window_heal():
    combat = _fight(
        "Pyke",
        auto=False,
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        enemy_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
    )
    incoming = _incoming(combat)
    for event in incoming:
        assert event["grey_health_stored"] == pytest.approx(
            0.09 * event["damage"], rel=0.01
        )
    survival = _main_survival(combat)
    assert survival["grey_health_stored"] == pytest.approx(
        0.09 * sum(e["damage"] for e in incoming), abs=0.1
    )
    assert survival["grey_health_consumed"] == 0.0
    assert (
        "out-of-vision" in survival["grey_health_source"]
        or "vision" in survival["grey_health_source"]
    )
    assert not [
        h
        for h in combat["healing_events"]
        if "Drowned" in h["source"] or "grey" in h["source"]
    ], "Pyke must not author an in-window grey heal"


def test_pyke_p_store_caps_at_eighty():
    combat = _fight("Pyke", auto=False, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    incoming = _incoming(combat)
    # 9% of the full burst exceeds the 80 flat cap (no bonus AD), so the
    # pool pins at 80.
    assert 0.09 * sum(e["damage"] for e in incoming) > 80.0
    assert _main_survival(combat)["grey_health_stored"] == pytest.approx(80.0)


def test_pyke_p_lethality_increases_the_store_ratio():
    combat = _fight(
        "Pyke",
        auto=False,
        items=["Youmuu's Ghostblade"],
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        enemy_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
    )
    lethality = float(_main_stats(combat)["lethality"])
    assert lethality > 0.0
    ratio = 0.09 + 0.002 * lethality
    incoming = _incoming(combat)
    for event in incoming:
        assert event["grey_health_stored"] == pytest.approx(
            ratio * event["damage"], rel=0.01
        )
    assert _main_survival(combat)["grey_health_stored"] == pytest.approx(
        ratio * sum(e["damage"] for e in incoming), abs=0.1
    )


def test_pyke_p_two_visible_enemies_uses_forty_percent():
    combat = _fight(
        "Pyke",
        auto=False,
        enemy_count=2,
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        enemy_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
    )
    incoming = _incoming(combat)
    for event in incoming:
        assert event["grey_health_stored"] == pytest.approx(
            0.40 * event["damage"], rel=0.01
        )
    # 40% of both Q-only bursts exceeds the 80 cap -> the pool pins at 80.
    assert 0.40 * sum(e["damage"] for e in incoming) > 80.0
    assert _main_survival(combat)["grey_health_stored"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Kled P (Skaarl) — documented revive-boundary, no authored heal
# ---------------------------------------------------------------------------


def test_kled_skaarl_pool_is_a_documented_revive_boundary():
    combat = _fight("Kled", auto=False, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    assert not [
        h for h in combat["healing_events"] if "Skaarl" in h["source"]
    ], "Kled must not author a Skaarl remount heal"
    survival = _main_survival(combat)
    assert not any(key.startswith("grey") for key in survival)
    from src.calculator.champions import kled as kled_module

    assumptions = " ".join(kled_module.ASSUMPTIONS)
    assert "Skaarl" in assumptions
    assert "revive-boundary" in assumptions


# ---------------------------------------------------------------------------
# Scoring paths stay number-identical for grey-health heals
# ---------------------------------------------------------------------------


def test_grey_health_score_walk_matches_legacy_score_receipts():
    from src.calculator.data_fetcher import get_champion
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.participant_timeline import (
        CoupledSearchContext,
        build_participant_timeline,
    )
    from src.calculator.pipeline import FightParams
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    champion = get_champion("Rengar")
    enemies = [
        ChampionLoadout(
            champion="Ahri", level=18, role="mid", items=(), boots=""
        ).resolve(),
        ChampionLoadout(
            champion="Annie", level=18, role="mid", items=(), boots=""
        ).resolve(),
    ]
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 16,
            "role": "top",
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "include_auto_attacks": True,
        },
        deterministic=True,
    )

    def timeline(**kwargs):
        stats = calculate_total_stats(champion, 18, [], role="top")
        defenses = resolve_starting_defenses(champion["name"], 18, stats, [])
        return build_participant_timeline(
            champion,
            18,
            [],
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    cache: dict = {}
    context = CoupledSearchContext()
    fast = timeline(
        pair_result_cache=cache, search_context=context, include_receipt=False
    )
    legacy = timeline(include_receipt=False)
    fast_survival = {p["participant_id"]: p["survival"] for p in fast["participants"]}
    for participant in legacy["participants"]:
        assert participant["survival"] == fast_survival[participant["participant_id"]]
    # The grey pool is part of both receipts.
    assert "grey_health_consumed" in fast_survival["main"]
    assert fast_survival["main"]["grey_health_consumed"] > 0.0
