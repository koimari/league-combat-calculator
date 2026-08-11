"""E1 heal-batch 3: sourced self-heal rules.

Each test runs a real /api/calculate fight through the app test client at
level 18 with rank 5/3 abilities and asserts the heal event(s) appear with
the value the cached Wiki data (data/champions.json) specifies:

- Alistar P  Triumphant Roar  5% max health per 7 Q/W stun+displace stacks
- Ekko R     Chronobreak      Minimum Heal 100/150/200 (+ 60% AP)
- Fiora P    Duelist's Dance  35 : 100 (based on level) per Vital proc
- Gangplank W Remove Scurvy   45-145 (+ 90% AP) (+ 13% missing health)
- Garen P    Perseverance     0.15% : 1.01% max health / 0.5s, lost for
                              8s after champion damage (combat gate)
- Gragas P   Happy Hour       5.5% max health per ability cast
- Gwen P     A Thousand Cuts  50% of post-mitigation passive damage,
                              capped at 10 : 25 (+ 6.5% AP) per instance
- Yorick Q   Last Rites       10 : 78 (based on level) (+ 6% : 10% missing
                              health, based on rank) against champions

Chogath P (Carnivore, kill-triggered) and Maokai P (Sap Magic, periodic
empowered-auto trigger) are deliberately not authored here: the 1v1 model
has no minion kills and no kill receipt, and Maokai's reviewed packet
declares P a no-damage slot with no empowered-auto event, so a rule would
fabricate a trigger the ledger never emits.
"""

import pytest

from src import app as app_module

_ENEMY = "Ahri"
_ENEMY_RANKS = {"Q": 5, "W": 5, "E": 0, "R": 3}
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(
    champion: str,
    *,
    items: list[str] | None = None,
    options: dict | None = None,
    duration: int = 10,
    enemy: str = _ENEMY,
    enemy_items: list[str] | None = None,
) -> dict:
    # pylint: disable=too-many-arguments
    payload = {
        "champion": champion,
        "level": 18,
        "items": items or [],
        "role": "mid",
        "ability_ranks": dict(_RANKS),
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "champion_options": options or {},
        "enemies": [
            {
                "champion": enemy,
                "level": 18,
                "items": enemy_items or [],
                "role": "mid",
                "ability_ranks": dict(_ENEMY_RANKS),
            }
        ],
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["combat"]


def _main_heals(combat: dict) -> list[dict]:
    return [e for e in combat.get("healing_events", []) if e.get("attacker") == "main"]


def _max_health(combat: dict) -> float:
    return float(combat["participants"][0]["survival"]["max_health"])


def _main_events(combat: dict) -> list[dict]:
    return [e for e in combat.get("events", []) if e.get("attacker") == "main"]


def _enemy_events(combat: dict) -> list[dict]:
    return [e for e in combat.get("events", []) if e.get("attacker") != "main"]


def test_alistar_triumphant_roar_heals_five_percent_max_health_per_seven_stacks():
    """Q (stun+knockup) and W (knockback) each grant one Triumph stack; at
    7 stacks the passive heals 5% of maximum health.  20 ability haste
    (Frozen Heart) lets the 30s window fit 4 Q + 4 W casts so the seventh
    Q/W event fires the heal.  Galio is the durable-but-soft enemy that
    keeps Alistar alive through the 7-stack window; Sion's corrected
    Decimating Smash (E5-1) out-damages that window."""
    combat = _fight(
        "Alistar",
        items=["Frozen Heart"],
        duration=30,
        enemy="Galio",
    )
    heals = [e for e in _main_heals(combat) if e["source"] == "Triumphant Roar"]
    assert heals, "Triumphant Roar heal missing"
    # Alistar level 18 base health 2725 (no HP on Frozen Heart); the wiki
    # text says "heal himself for 5% of his maximum health".
    assert heals[0]["raw_amount"] == pytest.approx(0.05 * _max_health(combat), abs=0.1)
    assert heals[0]["applied_amount"] > 0.0
    qw_events = [e for e in _main_events(combat) if e.get("source") in {"Q", "W"}]
    assert len(qw_events) >= 7
    # One heal for the single 7-stack completion in a 30s window.
    assert len(heals) == 1


def test_ekko_chronobreak_heals_sourced_minimum_heal():
    """R heals the rank-scaled Minimum Heal at detonation (100/150/200 +
    60% AP).  The 0%-300% health-lost-in-4s rider needs incoming-damage
    history the outgoing ledger does not carry, so the sourced minimum is
    the value this model pays.  Rank 3 flat = 200 with no AP."""
    combat = _fight("Ekko")
    heals = [e for e in _main_heals(combat) if e["source"] == "Chronobreak"]
    assert heals
    assert all(e["raw_amount"] == pytest.approx(200.0) for e in heals)


def test_ekko_chronobreak_minimum_heal_scales_with_ap():
    """Minimum Heal carries a 60% AP ratio; with Rabadon's Deathcap the
    rank-3 heal is 200 + 0.6 * AP."""
    combat = _fight("Ekko", items=["Rabadon's Deathcap"])
    heals = [e for e in _main_heals(combat) if e["source"] == "Chronobreak"]
    assert heals
    ap = float(combat["participants"][0]["stats"]["ability_power"])
    assert ap > 0.0
    assert heals[0]["raw_amount"] == pytest.approx(200.0 + 0.6 * ap, abs=0.1)


def test_fiora_duelists_dance_heals_flat_per_vital_proc():
    """Each Vital proc heals Fiora for 35 : 100 (based on level); at level
    18 the sourced per-level array ("Bonus Damage") reads 100."""
    combat = _fight("Fiora", options={"p_vitals": 4})
    heals = [e for e in _main_heals(combat) if e["source"] == "Duelist's Dance"]
    assert len(heals) == 4
    assert all(e["raw_amount"] == pytest.approx(100.0) for e in heals)


def test_gangplank_remove_scurvy_heals_flat_ap_and_missing_health():
    """W heals 145 + 90% AP + 13% missing health at cast (rank 5).  The
    cast has no damage event, so the heal rides the W cast; the
    missing-health term is re-priced by the survival ledger from the
    damage the enemy dealt before the cast."""
    combat = _fight("Gangplank")
    heals = [e for e in _main_heals(combat) if e["source"] == "Remove Scurvy"]
    assert heals
    heal = heals[0]
    assert heal["time"] == pytest.approx(0.25)
    # Enemy damage applied before the W cast at 0.25s (all enemy events
    # through that timestamp in walk order).
    taken_before = sum(
        e["damage"] for e in _enemy_events(combat) if float(e["time"]) <= 0.25
    )
    assert taken_before > 0.0
    expected = 145.0 + 0.13 * taken_before
    assert heal["raw_amount"] == pytest.approx(expected, abs=0.2)


def test_gangplank_remove_scurvy_heal_scales_with_ap():
    """The 90% AP ratio is paid on top of the flat heal and missing
    health term when the build carries Rabadon's Deathcap."""
    combat = _fight("Gangplank", items=["Rabadon's Deathcap"])
    heals = [e for e in _main_heals(combat) if e["source"] == "Remove Scurvy"]
    assert heals
    ap = float(combat["participants"][0]["stats"]["ability_power"])
    taken_before = sum(
        e["damage"] for e in _enemy_events(combat) if float(e["time"]) <= 0.25
    )
    assert heals[0]["raw_amount"] == pytest.approx(
        145.0 + 0.9 * ap + 0.13 * taken_before, abs=0.2
    )


def test_garen_perseverance_regen_is_lost_while_taking_champion_damage():
    """Perseverance regenerates 1.01% of max health per 0.5s at level 18
    but is lost for 8 seconds whenever Garen takes champion damage,
    refreshing on subsequent damage.  A 1v1 fight is continuous champion
    damage, so every tick must be authored and then suppressed by the
    timeline's combat gate — never silently applied."""
    combat = _fight("Garen")
    ticks = [e for e in _main_heals(combat) if e["source"] == "Perseverance"]
    assert len(ticks) >= 10
    assert all(e["applied_amount"] == 0.0 for e in ticks)
    assert all(e.get("skipped_reason") == "damage_free_window_not_ready" for e in ticks)


def test_gragas_happy_hour_heals_per_ability_cast():
    """Every ability cast heals Gragas for 5.5% of maximum health; the
    heal triggers on the cast even for abilities whose damage lands later
    (Barrel Roll) or not at all."""
    combat = _fight("Gragas")
    heals = [e for e in _main_heals(combat) if e["source"].startswith("Happy Hour")]
    assert heals
    expected = 0.055 * _max_health(combat)
    assert all(e["raw_amount"] == pytest.approx(expected, abs=0.1) for e in heals)
    # One receipt per cast: Q, W, E, R at the opening, W and Q again later.
    sources = sorted(e["source"] for e in heals)
    assert len(sources) == 6
    assert len(set(sources)) == 4


def test_gwen_a_thousand_cuts_heals_half_post_mitigation_damage_capped():
    """The passive heals 50% of the post-mitigation damage dealt against
    champions, capped per instance at 10 : 25 (based on level) + 6.5% AP
    (level 18 cap = 25, so the small on-hit instances are uncapped)."""
    combat = _fight("Gwen")
    heals = [e for e in _main_heals(combat) if e["source"] == "A Thousand Cuts"]
    assert heals
    events_by_time = {
        float(e["time"]): e
        for e in _main_events(combat)
        if e["source"] == "on_hit_ability_passive"
    }
    for heal in heals:
        event = events_by_time.get(round(float(heal["time"]), 3))
        assert event is not None, f"no passive event at {heal['time']}"
        expected = min(0.5 * float(event["damage"]), 25.0)
        assert heal["raw_amount"] == pytest.approx(expected, abs=0.1)


def test_yorick_last_rites_heals_flat_plus_missing_health_against_champion():
    """The empowered attack heals 10 : 78 (based on level) + 6% : 10%
    (based on rank) of missing health against champions; rank 5 at level
    18 is 78 + 10% of the health lost to the enemy before the hit."""
    combat = _fight("Yorick")
    heals = [e for e in _main_heals(combat) if e["source"] == "Last Rites"]
    assert heals
    heal = heals[0]
    assert heal["time"] == pytest.approx(0.0)
    taken_at_zero = sum(
        e["damage"] for e in _enemy_events(combat) if float(e["time"]) == 0.0
    )
    assert taken_at_zero > 0.0
    expected = 78.0 + 0.10 * taken_at_zero
    assert heal["raw_amount"] == pytest.approx(expected, abs=0.2)
