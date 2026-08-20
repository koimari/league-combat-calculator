"""E1-b4: sourced self-heal rules for Tahm Kench, Tryndamere, Volibear, Zac.

Every asserted number traces to ``data/champions.json`` leveling attributes:

- Tahm Kench Q (Tongue Lash): flat + % of missing health per champion hit
  (``Heal`` = 10/15/20/25/30 flat + 5/5.5/6/6.5/7% of missing health).
- Tryndamere Q (Bloodlust): consumes Fury to heal; the fight model does not
  track Fury, so the sourced receipt is the 0-Fury minimum (``Minimum Heal``
  = 30/40/50/60/70 + 30% AP).
- Volibear W (Frenzied Maul): Wounded-bonus bite heals flat + % of missing
  health (``Heal`` = 20/35/50/65/80 flat + 8/11/14/17/20% of missing
  health); the first W applies the Wound, every later W heals.
- Zac P (Cell Division): each ability hit drops a Goo chunk consumed to
  heal for ``Max Health Damage`` = 4% : 8.47% (based on level) of maximum
  health (8.0% at level 18).

Pyke P is a grey-health heal sourced from post-mitigation damage TAKEN
(plus an out-of-vision requirement); the fight ledger only carries damage
dealt, so it does not apply to the 1v1 model (E8a documents the vision
boundary). Rengar W is now implemented by the E8a grey-health primitive
(see tests/test_e8_grey_health.py). Udyr's base W on-hit heal exists only
in prose (no leveling attribute), and its leveling-sourced heal stream
belongs to the Awakened recast the fight model does not model — those two
remain skipped by the rule set.
"""

import pytest

from src import app as app_module

_ENEMY_NAMES = ["Ahri", "Annie", "Orianna"]


def _fight(
    champion: str,
    *,
    level: int = 18,
    ranks: dict | None = None,
    ap_item: str | None = None,
    enemies: int = 1,
    enemy_ranks: dict | None = None,
    auto_attacks: bool = True,
) -> dict:
    """Run one /api/calculate time-based fight and return the combat ledger."""
    payload = {
        "champion": champion,
        "level": level,
        "items": [ap_item] if ap_item else [],
        "role": "mid",
        **({"ability_ranks": ranks} if ranks is not None else {}),
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": auto_attacks,
        "enemies": [
            {
                "champion": _ENEMY_NAMES[index % len(_ENEMY_NAMES)],
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": enemy_ranks or {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
            for index in range(enemies)
        ],
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _main_heals(combat: dict) -> list[dict]:
    return [e for e in combat.get("healing_events", []) if e.get("attacker") == "main"]


def _main_stats(combat: dict) -> dict:
    return next(p for p in combat["participants"] if p["participant_id"] == "main")[
        "stats"
    ]


# A zero-rank enemy with no auto attacks deals no damage, so the attacker
# stays at full health and every missing-health heal equals its flat part.
_NO_DAMAGE_RANKS = {"Q": 0, "W": 0, "E": 0, "R": 0}


def test_tahm_kench_tongue_lash_heals_sourced_flat_value_at_full_health():
    combat = _fight(
        "TahmKench",
        ranks={"Q": 1, "W": 5, "E": 5, "R": 3},
        enemy_ranks=_NO_DAMAGE_RANKS,
        auto_attacks=False,
    )
    heals = _main_heals(combat)
    assert heals, "Tongue Lash heal missing"
    assert {h["source"] for h in heals} == {"Tongue Lash"}
    # rank 1 flat heal = 10 (data/champions.json "Heal" modifier 0); the
    # 5% of missing health resolves to 0 at full health.
    assert all(h["raw_amount"] == pytest.approx(10.0) for h in heals)


def test_tahm_kench_tongue_lash_scales_with_missing_health():
    combat = _fight("TahmKench", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    heals = [h for h in _main_heals(combat) if h["source"] == "Tongue Lash"]
    assert len(heals) >= 1
    # rank 5 flat = 30; every heal must exceed the flat part because the
    # fighter has taken damage by the time Q lands, and later heals must
    # out-heal earlier ones (more missing health).
    assert all(h["raw_amount"] > 30.0 for h in heals)
    assert all(h["applied_amount"] > 0.0 for h in heals)
    assert heals[-1]["raw_amount"] > heals[0]["raw_amount"]


def test_volibear_frenzied_maul_heals_only_the_wounded_bite():
    combat = _fight(
        "Volibear",
        ranks={"Q": 5, "W": 1, "E": 5, "R": 3},
        enemy_ranks=_NO_DAMAGE_RANKS,
        auto_attacks=False,
    )
    heals = _main_heals(combat)
    # The first W applies the Wound; only the second W (the bite) heals.
    assert len(heals) == 1
    assert heals[0]["source"] == "Frenzied Maul"
    # rank 1 flat heal = 20 ("Heal" modifier 0); 8% of missing health is 0
    # at full health.
    assert heals[0]["raw_amount"] == pytest.approx(20.0)
    # The bite lands at its cast time, not at the cast instant: "Frenzied
    # Maul deals bonus damage and heals if the target is still Wounded
    # after the cast time" (cached W note) and that cast time is 0.25s, so
    # the second W at 5.25 heals at 5.5.  One bite, one heal, however many
    # parts the module prices the bite with.
    assert heals[0]["time"] == pytest.approx(5.5)


def test_volibear_frenzied_maul_scales_with_missing_health():
    combat = _fight("Volibear", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    heals = [h for h in _main_heals(combat) if h["source"] == "Frenzied Maul"]
    assert heals, "Frenzied Maul heal missing"
    # rank 5 flat = 80; the bite lands after the fighter has taken damage.
    assert all(h["raw_amount"] > 80.0 for h in heals)
    assert all(h["applied_amount"] > 0.0 for h in heals)


def test_tryndamere_bloodlust_heals_minimum_scaled_by_ap():
    combat = _fight(
        "Tryndamere",
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        ap_item="Rabadon's Deathcap",
    )
    heals = [h for h in _main_heals(combat) if h["source"] == "Bloodlust"]
    assert heals, "Bloodlust heal missing"
    ap = float(_main_stats(combat)["ability_power"])
    assert ap > 0.0, "Deathcap must grant ability power"
    # rank 5 "Minimum Heal" = 70 flat + 30% AP (data/champions.json).
    expected = 70.0 + 0.30 * ap
    assert all(h["amount"] == pytest.approx(expected) for h in heals)
    assert all(h["raw_amount"] == pytest.approx(expected, rel=0.01) for h in heals)


def test_zac_cell_division_heals_percent_max_health_per_ability_hit():
    combat = _fight("Zac", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    heals = [h for h in _main_heals(combat) if h["source"] == "Cell Division"]
    assert heals, "Cell Division heal missing"
    ability_events = [
        e
        for e in combat.get("events", [])
        if e.get("attacker") == "main" and e.get("source") in {"Q", "W", "E", "R"}
    ]
    assert len(heals) == len(ability_events)
    max_health = float(_main_stats(combat)["health"])
    # level 18 passive value = 8.0 (% of max health per chunk).
    expected = max_health * 8.0 / 100.0
    assert all(h["raw_amount"] == pytest.approx(expected, rel=0.01) for h in heals)


def test_skipped_champions_have_no_self_heal_rule():
    # Pyke P heals from damage taken only while out of enemy vision; the
    # 1v1 ledger does not model vision, so the E8a grey-health primitive
    # stores the pool but authors no in-window heal (see
    # tests/test_e8_grey_health.py). Rengar W is implemented by E8a and
    # was removed from this skip list. (Udyr's W Iron Mantle heal is now
    # implemented — see test_e3_udyr_yuumi_heals.py.)
    combat = _fight("Pyke", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    assert not _main_heals(combat), "Pyke must not self-heal in-window"
