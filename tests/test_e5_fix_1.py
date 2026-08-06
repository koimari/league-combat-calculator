"""E5-1: corrected mis-modeled rows.

Each test runs a real /api/calculate fight through the app test client
(level 18, Q/W/E rank 5, R rank 3, no items) and asserts the corrected
damage, computed from the same ``data/champions.json`` leveling rows the
module now reads:

- Tryndamere Q (Bloodlust): the spurious 5/10/15/20/25 magic-damage row
  is removed — Q is a heal (the wiki has no enemy-damage attribute for
  it); the E1 Bloodlust heal still fires from the Q cast timeline.
- Zed R (Death Mark): 100% AD + 25/40/55% of stored pre-mitigation
  spell damage, instead of a flat ~AD hit that dropped the "% of damage
  stored" term.
- Twisted Fate W (Pick a Card): exactly one selected card (gold/red/blue
  via ``w_card``) instead of the sum of all three cards.
- Kled W (Violent Tendencies): the fourth-attack bonus reads the actual
  W rank instead of the champion level.
- Sion Q (Decimating Smash): Minimum/Maximum Physical Damage rows
  interpolated by charge fraction instead of the "Maximum Base Damage
  Increase" percentage read as flat.
- Veigar R (Primordial Burst): Minimum Magic Damage base scaled by the
  missing-health execute curve instead of the unconditional Maximum row.
"""

import json

import pytest

from src import app as app_module

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(
    champion: str,
    *,
    ranks: dict | None = None,
    options: dict | None = None,
    target_health: float = 1000.0,
    enemy: str = "Ahri",
    level: int = 18,
    enemies: list | None = None,
) -> dict:
    """Run one /api/calculate one-rotation fight and return the full JSON."""
    if enemies is None:
        enemies = [
            {
                "champion": enemy,
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": dict(_RANKS),
            }
        ]
    payload = {
        "champion": champion,
        "level": level,
        "items": [],
        "role": "mid",
        "ability_ranks": ranks or dict(_RANKS),
        "champion_options": options or {},
        "target_health": target_health,
        "fight_mode": "one_rotation",
        "include_auto_attacks": False,
        "enemies": enemies,
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _main_sources(data: dict) -> dict[str, float]:
    """Main participant's per-ability fight damage by ability name."""
    for participant in data["combat"]["breakdown"]:
        if participant["participant_id"] == "main":
            return {
                source["name"]: source["total_damage"]
                for source in participant["sources"]
            }
    raise AssertionError("main participant missing")


def _main_stats(data: dict) -> dict:
    return next(
        p for p in data["combat"]["participants"] if p["participant_id"] == "main"
    )["stats"]


def _enemy_stats(data: dict) -> dict:
    return next(
        p for p in data["combat"]["participants"] if p["participant_id"] != "main"
    )["stats"]


def _mitigated(raw: float, resistance: float) -> float:
    """Post-mitigation damage for one raw hit against a resistance."""
    return raw * 100.0 / (100.0 + resistance)


def _parse(champion: str, *, ranks: dict | None = None, options: dict | None = None):
    """Parse abilities with the same stats the app fight computed."""
    from src.calculator.champions import parse_champion_abilities

    with open("data/champions.json", encoding="utf-8") as handle:
        champion_data = next(
            value
            for value in json.load(handle).values()
            if value.get("name") == champion
        )
    stats = _fight(champion, ranks=ranks, options=options)["champion_stats"]
    return parse_champion_abilities(
        champion_data,
        18,
        float(stats["ability_power"]),
        ability_ranks=ranks or dict(_RANKS),
        champion_stats=stats,
        target_stats={
            "target_max_health": 1000.0,
            "target_current_health": 1000.0,
            "target_missing_health": 0.0,
        },
        champion_options=options or {},
    )


# ---------------------------------------------------------------------------
# Tryndamere — Q is a heal; the spurious magic-damage row is removed
# ---------------------------------------------------------------------------


def test_tryndamere_q_deals_no_damage():
    data = _fight("Tryndamere")
    abilities = _parse("Tryndamere")
    assert abilities["Q"]["total_raw"] == 0.0
    assert abilities["Q"]["parts"] == ()
    sources = _main_sources(data)
    assert "Bloodlust" not in sources
    # Spinning Slash (rank 5: 240 flat + 100% bonus AD + 80% AP) is the
    # only ability damage; bonus AD and AP are 0 with no items.
    assert "Spinning Slash" in sources
    assert sources["Spinning Slash"] == pytest.approx(
        _mitigated(240.0, float(data["effective_armor"])), abs=0.06
    )


def test_tryndamere_bloodlust_heal_still_fires_after_row_removal():
    """E1's Bloodlust heal must survive the removal of the Q damage row."""
    data = _fight("Tryndamere")
    heals = [
        event
        for event in data["combat"]["healing_events"]
        if event.get("attacker") == "main" and event.get("source") == "Bloodlust"
    ]
    assert heals, "Bloodlust heal missing after Q damage-row removal"
    # Minimum Heal rank 5 = 70 flat + 30% AP; no items -> 0 AP.
    assert all(event["raw_amount"] == pytest.approx(70.0) for event in heals)


# ---------------------------------------------------------------------------
# Zed — Death Mark stores a portion of the rotation's damage
# ---------------------------------------------------------------------------


def test_zed_death_mark_prices_stored_damage_percentage():
    abilities = _parse("Zed")
    stats = _fight("Zed")["champion_stats"]
    ad = float(stats["attack_damage"])
    q_raw = 240.0  # rank 5 flat; bonus AD 0
    e_raw = 160.0  # rank 5 flat; bonus AD 0
    # Physical Damage row: 100% AD + 55% of damage stored (rank 3).
    expected = ad + 0.55 * (q_raw + e_raw)
    assert abilities["R"]["total_raw"] == pytest.approx(expected)
    assert abilities["R"]["rank"] == 3


def test_zed_death_mark_fight_damage_matches_stored_formula():
    data = _fight("Zed")
    ad = float(data["champion_stats"]["attack_damage"])
    expected_raw = ad + 0.55 * (240.0 + 160.0)
    sources = _main_sources(data)
    assert sources["Death Mark"] == pytest.approx(
        _mitigated(expected_raw, float(data["effective_armor"])), abs=0.06
    )


# ---------------------------------------------------------------------------
# Twisted Fate — Pick a Card prices exactly one selected card
# ---------------------------------------------------------------------------


def test_twisted_fate_w_prices_one_card():
    stats = _fight("Twisted Fate")["champion_stats"]
    ad = float(stats["attack_damage"])
    ap = float(stats["ability_power"])
    # Gold Card (default): 15/22.5/30/37.5/45 + 100% AD + 50% AP.
    gold = _parse("Twisted Fate")["W"]
    assert gold["total_raw"] == pytest.approx(45.0 + ad + 0.5 * ap)
    assert gold["name"] == "Gold Card"
    # Red Card: 30/45/60/75/90 + 100% AD + 70% AP.
    red = _parse("Twisted Fate", options={"w_card": 1})["W"]
    assert red["total_raw"] == pytest.approx(90.0 + ad + 0.7 * ap)
    # Blue Card: 40/60/80/100/120 + 100% AD + 100% AP.
    blue = _parse("Twisted Fate", options={"w_card": 2})["W"]
    assert blue["total_raw"] == pytest.approx(120.0 + ad + ap)


def test_twisted_fate_w_fight_uses_gold_card_default():
    data = _fight("Twisted Fate")
    ad = float(data["champion_stats"]["attack_damage"])
    ap = float(data["champion_stats"]["ability_power"])
    expected_raw = 45.0 + ad + 0.5 * ap
    sources = _main_sources(data)
    assert sources["Gold Card"] == pytest.approx(
        _mitigated(expected_raw, float(data["effective_mr"])), abs=0.06
    )
    assert "Pick a Card" not in sources


# ---------------------------------------------------------------------------
# Kled — Violent Tendencies reads the actual W rank
# ---------------------------------------------------------------------------


def test_kled_w_reads_actual_rank_not_level():
    for w_rank, flat, max_hp_pct in ((1, 20.0, 4.5), (3, 40.0, 5.5), (5, 60.0, 6.5)):
        entry = _parse("Kled", ranks={"Q": 5, "W": w_rank, "E": 5, "R": 3})["W"]
        # The entry's rank is the W rank, never the champion level.
        assert entry["rank"] == w_rank
        # Additional Physical Damage: flat + % of target's maximum health;
        # bonus AD / bonus health terms are 0 with no items and a 1000 HP
        # target.
        assert entry["total_raw"] == pytest.approx(flat + (max_hp_pct / 100.0) * 1000.0)


def test_kled_w_fight_uses_actual_w_rank():
    data = _fight(
        "Kled",
        ranks={"Q": 5, "W": 3, "E": 5, "R": 3},
    )
    main_stats = _main_stats(data)
    enemy_stats = _enemy_stats(data)
    # Rank 3: 40 flat + 5.5% of the target's maximum health; with no auto
    # stream the empowered fourth attack also carries the forced swing
    # (100% AD).  The target is the enemy champion, so its max health is
    # the enemy's actual health.
    expected_raw = (
        40.0
        + (5.5 / 100.0) * float(enemy_stats["health"])
        + float(main_stats["attack_damage"])
    )
    sources = _main_sources(data)
    assert sources["Violent Tendencies"] == pytest.approx(
        _mitigated(expected_raw, float(data["effective_armor"])), abs=0.06
    )


# ---------------------------------------------------------------------------
# Sion — Decimating Smash uses the Min/Max Physical Damage rows
# ---------------------------------------------------------------------------


def test_sion_q_uses_min_max_physical_damage_rows():
    stats = _fight("Sion")["champion_stats"]
    ad = float(stats["attack_damage"])
    # Maximum Physical Damage rank 5: 350 + 240% AD (fully charged default).
    maxed = _parse("Sion")["Q"]
    assert maxed["total_raw"] == pytest.approx(350.0 + 2.4 * ad)
    # Minimum Physical Damage rank 5: 90 + 80% AD.
    min_charge = _parse("Sion", options={"q_charge_fraction": 0.0})["Q"]
    assert min_charge["total_raw"] == pytest.approx(90.0 + 0.8 * ad)
    # Half charge interpolates between the two rows.
    half = _parse("Sion", options={"q_charge_fraction": 0.5})["Q"]
    assert half["total_raw"] == pytest.approx(
        (90.0 + 0.8 * ad + 350.0 + 2.4 * ad) / 2.0
    )


def test_sion_q_fight_damage_uses_maximum_physical_damage():
    data = _fight("Sion")
    ad = float(data["champion_stats"]["attack_damage"])
    expected_raw = 350.0 + 2.4 * ad
    sources = _main_sources(data)
    # F3 shred-first derivation: E (Roar of the Slayer) opens the rotation,
    # so the 25% armor-reduction shred is applied BEFORE Q's own hit — the
    # fully charged Decimating Smash mitigates at the shredded armor.
    enemy_armor = float(_enemy_stats(data)["armor"])
    assert sources["Decimating Smash"] == pytest.approx(
        _mitigated(expected_raw, enemy_armor * 0.75), abs=0.06
    )


# ---------------------------------------------------------------------------
# Veigar — Primordial Burst uses the base + execute condition
# ---------------------------------------------------------------------------


def test_veigar_r_uses_minimum_base_not_unconditional_maximum():
    abilities = _parse("Veigar")
    # Minimum Magic Damage rank 3: 325 + 75% AP; no items -> 0 AP.
    assert abilities["R"]["total_raw"] == pytest.approx(325.0)
    assert abilities["R"]["rank"] == 3


def test_veigar_r_fight_damage_scales_with_missing_health():
    data = _fight("Veigar")
    mr = float(data["effective_mr"])
    sources = _main_sources(data)
    # The target has taken only Q + W (mitigated) by the time R lands:
    # missing ratio < 2/3, so the execute boost is 0 and R prices the
    # Minimum row (325).
    assert sources["Primordial Burst"] == pytest.approx(_mitigated(325.0, mr), abs=0.06)

    # A 300 HP target (no-enemy path uses the request's target health) is
    # below 33% health by the time R lands: Q (120) + W (152.5) leave 27.5
    # HP, missing ratio 0.9083 -> boost 0.725 -> raw 325 * 1.725 = 560.6.
    low = _fight("Veigar", target_health=300.0, enemies=[])
    low_mr = float(low["effective_mr"])
    low_r = low["breakdown"]["R"]["total_damage"]
    assert low_r == pytest.approx(_mitigated(560.625, low_mr), abs=0.06)
    assert low_r > _mitigated(325.0, low_mr)
    assert low_r <= _mitigated(650.0, low_mr)
