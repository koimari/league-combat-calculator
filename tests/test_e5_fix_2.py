"""E5-2: fix mis-modeled champion rows (batch 2 — wrong reads).

One test per champion drives an ``/api/calculate`` one-rotation fight at
level 18 (basic abilities rank 5, ultimates rank 3, no items, target
armor/MR 0 so post-mitigation damage equals the raw wiki values) and
asserts the corrected damage against values recomputed from
``data/champions.json`` leveling rows plus the fight's own champion
stats.  Every asserted number traces to the wiki cache (or documented
wiki prose pinned in the champion module, cited there).

Fixes under test:

- Nautilus P: the packet read the root-duration "Bonus Damage" row
  (0.75-1.5) as flat damage and dropped the 14 : 128 per-level bonus
  physical damage ("Per-Level Scaling") — now an on-hit.
- Poppy    P: the packet kept only the %max-HP "Max Health Damage" row
  (actually the buckler-retrieval SHIELD) and dropped the 20 : 198.82
  per-level "Bonus Magic Damage" — now an on-hit.
- Nilah    Q: pinned to the crit-MAX "Maximum Physical Damage" row
  (0-76.4 + 191% AD) as flat — now the 0%-crit "Minimum Physical
  Damage" row (0-40 + 100% AD), scaled by crit chance.
- Pyke     R: the 1.5x-threshold array (375-825) pinned to the first
  three ranks, magic — now the sourced non-execute damage row
  (125 : 275 per level + 40% bAD + 0.75 per Lethality, physical).
- Mel      W: reflected-projectile modifier (40-60%) read as flat — now
  a documented no-damage slot.  R: only the flat "Magic Damage" row —
  now plus (4/7/10 + 4% AP) per Overwhelm stack (option).
- Zoe      W: one flat bolt (15-55 + 10% AP) — now the three-bolt
  "Total Magic Damage" row (45-165 + 30% AP); Heal/Barrier/Smite
  Spell-Shard mimics are option-gated no-damage rows.
- Riven    P: declared no_damage — now an on-hit at 30% : 46.76%
  (based on level) AD per stack.
- Zeri     E: one flat Lightning Rounds hit (22-30 + 20% AP) — now 7
  Burst Fire rounds of the bonus (the E2-sourced round count on Q).
- Quinn    P: Harrier on-hit declared out_of_scope — now an on-hit at
  15 : 132.35 (based on level) (+ 40% bonus AD).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_CACHE_KEY_BY_DISPLAY = {
    str(value.get("name", "")): key
    for key, value in _CHAMPION_DATA.items()
    if isinstance(value, dict) and str(value.get("name", "")).strip()
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(
    champion: str,
    *,
    options: dict | None = None,
    include_autos: bool = False,
) -> dict:
    """One /api/calculate one-rotation fight at level 18, no items.

    Target armor/MR are zeroed so post-mitigation damage equals the raw
    wiki values; ``include_autos`` arms the auto stream (explicit
    100% uptime) for the on-hit passive assertions.
    """
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": dict(_FULL_RANKS),
        "fight_mode": "one_rotation",
        "fight_duration": 10,
        "include_auto_attacks": include_autos,
        "auto_attack_uptime": 1.0,
        "auto_attack_uptime_mode": "explicit",
        "target_health": 2000,
        "target_armor": 0,
        "target_mr": 0,
    }
    if options:
        payload["champion_options"] = options
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _value(champion: str, slot: str, attribute: str, rank: int) -> float:
    """Sum one leveling row at rank from data/champions.json.

    Handles exactly the unit vocabularies the tested rows use; an
    unexpected unit fails loudly so the test cannot silently pass with a
    dropped term.
    """
    ability = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            total = 0.0
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values:
                    continue
                idx = min(max(rank, 1) - 1, len(values) - 1)
                unit = units[idx] if idx < len(units) else ""
                if unit in ("", "%"):
                    total += float(values[idx])
                elif unit in ("% AD", "% bonus AD", "% AP"):
                    # No items: every scaling stat is 0, so these terms are
                    # 0.0 here; AD/AP-scaled tests add them explicitly from
                    # the fight's own stats.
                    total += 0.0
                else:
                    raise AssertionError(f"unexpected unit {unit!r} in {attribute}")
            return total
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


def _on_hit_row(data: dict) -> dict:
    row = data["breakdown"]["on_hit_ability_passive"]
    assert row["count"] > 0
    return row


def _parse(champion: str, data: dict) -> dict:
    """Parse one champion's abilities against the fight's own stats.

    The fight response does not expose per-row damage types, so the
    corrected type (Pyke R physical, Zeri E magic, ...) is asserted at
    the parse boundary with the exact fight stats.
    """
    from src.calculator.champions import parse_champion_abilities

    champion_data = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]
    return parse_champion_abilities(
        champion_data,
        18,
        data["champion_stats"]["ability_power"],
        ability_ranks=dict(_FULL_RANKS),
        champion_stats=data["champion_stats"],
        target_stats={
            "target_max_health": data["target_effective_max_health"],
            "target_current_health": data["target_effective_max_health"],
            "target_missing_health": 0.0,
        },
    )


# ---------------------------------------------------------------------------
# Nautilus — Staggering Blow (P): 14 : 128 per-level bonus physical damage
# ---------------------------------------------------------------------------


def test_nautilus_p_prices_the_per_level_bonus_physical_damage():
    """Level 18: the 'Per-Level Scaling' row is 116 bonus physical damage
    per empowered auto (the old packet priced the 0.75-1.5 root duration)."""
    data = _fight("Nautilus", include_autos=True)
    per_hit = _value("Nautilus", "P", "Per-Level Scaling", 18)
    assert per_hit == pytest.approx(116.0)
    row = _on_hit_row(data)
    assert row["name"] == "Staggering Blow (on-hit)"
    assert row["damage_per_hit"] == pytest.approx(per_hit)
    assert row["total_damage"] == pytest.approx(per_hit * row["count"], abs=0.06)
    assert _parse("Nautilus", data)["passive"]["on_hit"]["damage_type"] == "physical"


# ---------------------------------------------------------------------------
# Poppy — Iron Ambassador (P): 20 : 198.82 per-level bonus magic damage
# ---------------------------------------------------------------------------


def test_poppy_p_prices_the_flat_bonus_magic_damage():
    """Level 18: the 'Bonus Magic Damage' row is 180 bonus magic damage
    per empowered buckler toss (the old packet priced only the %max-HP
    shield row at zero base)."""
    data = _fight("Poppy", include_autos=True)
    per_hit = _value("Poppy", "P", "Bonus Magic Damage", 18)
    assert per_hit == pytest.approx(180.0)
    row = _on_hit_row(data)
    assert row["name"] == "Iron Ambassador (on-hit)"
    assert row["damage_per_hit"] == pytest.approx(per_hit)
    assert row["total_damage"] == pytest.approx(per_hit * row["count"], abs=0.06)
    assert _parse("Poppy", data)["passive"]["on_hit"]["damage_type"] == "magic"


# ---------------------------------------------------------------------------
# Nilah — Formless Blade (Q): Minimum Physical Damage row at 0% crit
# ---------------------------------------------------------------------------


def test_nilah_q_prices_the_minimum_row_not_the_crit_max():
    """Rank 5, 0% crit: Q deals the 'Minimum Physical Damage' row
    (40 + 100% AD) — the old packet pinned the crit-max 191% AD row."""
    data = _fight("Nilah")
    ad = data["champion_stats"]["attack_damage"]
    expected = 40.0 + ad  # Minimum Physical Damage row: 40 flat + 100% AD
    q = data["breakdown"]["Q"]
    assert q["total_damage"] == pytest.approx(expected, abs=0.06)
    assert "Minimum Physical Damage" in q["detail"]
    # The old crit-max value (76.4 + 191% AD) must not be what is priced.
    assert q["total_damage"] != pytest.approx(76.4 + 1.91 * ad)
    assert _parse("Nilah", data)["Q"]["damage_type"] == "physical"


def test_nilah_q_scales_with_crit_chance_between_the_sourced_endpoints():
    """At 100% crit the Q prices exactly the cached Maximum row (1.91x);
    at 0% crit it prices the Minimum row — both endpoints sourced."""
    from src.calculator.champions import parse_champion_abilities

    champion = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY["Nilah"]]
    stats = {
        "attack_damage": 200.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 100.0,
        "ability_power": 0.0,
        "critical_strike_chance": 100.0,
    }
    parsed = parse_champion_abilities(
        champion,
        18,
        0.0,
        ability_ranks=dict(_FULL_RANKS),
        champion_stats=stats,
        target_stats={"target_max_health": 2000.0},
    )
    # 0-40 base + 100% AD at 0% crit, x1.91 at 100% crit == the Maximum row.
    assert parsed["Q"]["total_raw"] == pytest.approx(
        (40.0 + 1.0 * 200.0) * 1.91, abs=0.06
    )
    assert parsed["Q"]["total_raw"] == pytest.approx(76.4 + 1.91 * 200.0, abs=0.06)


# ---------------------------------------------------------------------------
# Pyke — Death from Below (R): sourced non-execute damage row
# ---------------------------------------------------------------------------


def test_pyke_r_prices_the_non_execute_damage_row():
    """Level 18, no items: R deals 275 + 40% bAD + 0.75 per Lethality
    physical (the 50%-of-threshold damage row), not the old 1.5x-
    threshold 495 magic pinned to rank 3."""
    data = _fight("Pyke")
    b_ad = data["champion_stats"]["bonus_attack_damage"]
    lethality = data["champion_stats"]["lethality"]
    expected = 275.0 + 0.40 * b_ad + 0.75 * lethality
    r = data["breakdown"]["R"]
    assert r["total_damage"] == pytest.approx(expected, abs=0.06)
    assert _parse("Pyke", data)["R"]["damage_type"] == "physical"
    assert "Non-execute damage" in r["detail"]
    assert r["total_damage"] != pytest.approx(495.0)


# ---------------------------------------------------------------------------
# Mel — Rebuttal (W) no damage; Golden Eclipse (R) + per-stack term
# ---------------------------------------------------------------------------


def test_mel_w_no_longer_prices_the_reflection_modifier_as_flat_damage():
    """W prices 0 damage: the 40-60% 'Replicated Projectile Magic Damage
    Modifier' is a percentage of an enemy projectile, and no enemy
    projectile source is modeled."""
    data = _fight("Mel")
    w = data["breakdown"]["W"]
    assert w["total_damage"] == pytest.approx(0.0)
    assert "no enemy projectile source" in w["detail"]


def test_mel_r_prices_the_per_overwhelm_stack_term():
    """Rank 3, 0 AP, default 3 Overwhelm stacks: R = 275 + 10 x 3 =
    305 magic (the old packet read only the flat 275)."""
    data = _fight("Mel")
    r = data["breakdown"]["R"]
    assert r["total_damage"] == pytest.approx(275.0 + 10.0 * 3, abs=0.06)
    assert _parse("Mel", data)["R"]["damage_type"] == "magic"
    assert "per Overwhelm stack" in r["detail"]


def test_mel_r_overwhelm_stacks_option_scales_the_detonation():
    data = _fight("Mel", options={"r_overwhelm_stacks": 7})
    assert data["breakdown"]["R"]["total_damage"] == pytest.approx(
        275.0 + 10.0 * 7, abs=0.06
    )


# ---------------------------------------------------------------------------
# Zoe — Spell Thief (W): three bolts = the Total Magic Damage row
# ---------------------------------------------------------------------------


def test_zoe_w_prices_all_three_bolts():
    """Rank 5: W deals the 'Total Magic Damage' row (165 = 3 x 55), not
    the single 55 bolt the old packet priced."""
    data = _fight("Zoe")
    w = data["breakdown"]["W"]
    total = _value("Zoe", "W", "Total Magic Damage", 5)
    assert total == pytest.approx(165.0)
    assert w["total_damage"] == pytest.approx(total, abs=0.06)
    assert w["total_damage"] != pytest.approx(55.0)


@pytest.mark.parametrize("summoner,reason", [(1, "Heal"), (2, "Barrier"), (3, "Smite")])
def test_zoe_w_summoner_shard_variants_price_no_champion_damage(summoner, reason):
    data = _fight("Zoe", options={"w_summoner": summoner})
    w = data["breakdown"]["W"]
    assert w["total_damage"] == pytest.approx(0.0)
    assert reason in w["detail"]


# ---------------------------------------------------------------------------
# Riven — Runic Blade (P): per-level % AD on-hit
# ---------------------------------------------------------------------------


def test_riven_p_prices_the_per_level_ad_ratio():
    """Level 18: Runic Blade deals AD x 45% bonus physical damage per
    empowered auto (the 30% : 46.76% per-level row)."""
    data = _fight("Riven", include_autos=True)
    ad = data["champion_stats"]["attack_damage"]
    percent = _value("Riven", "P", "Per-Level Scaling", 18)
    assert percent == pytest.approx(45.0)  # level 18 -> index 17
    expected = ad * percent / 100.0
    row = _on_hit_row(data)
    assert row["name"] == "Runic Blade (on-hit)"
    assert row["damage_per_hit"] == pytest.approx(expected, abs=0.06)
    assert row["total_damage"] == pytest.approx(expected * row["count"], abs=0.6)
    assert _parse("Riven", data)["passive"]["on_hit"]["damage_type"] == "physical"


# ---------------------------------------------------------------------------
# Zeri — Spark Surge (E): 7 Lightning-Rounds-empowered Burst Fire rounds
# ---------------------------------------------------------------------------


def test_zeri_e_prices_seven_lightning_rounds_rounds():
    """Rank 5, 0 AP: E = 7 Burst Fire rounds x 30 bonus magic damage =
    210 (the old packet priced one 30-damage hit)."""
    data = _fight("Zeri")
    per_round = _value("Zeri", "E", "Burst Fire Bonus Magic Damage", 5)
    assert per_round == pytest.approx(30.0)
    e = data["breakdown"]["E"]
    assert e["total_damage"] == pytest.approx(per_round * 7, abs=0.06)
    assert e["total_damage"] != pytest.approx(30.0)
    assert _parse("Zeri", data)["E"]["damage_type"] == "magic"
    assert "Burst Fire rounds" in e["detail"]


# ---------------------------------------------------------------------------
# Quinn — Harrier (P): per-level on-hit + 40% bonus AD
# ---------------------------------------------------------------------------


def test_quinn_p_prices_the_harrier_on_hit():
    """Level 18, no items: Harrier deals 120 (+ 40% bAD) bonus physical
    damage per marked-target auto — the old packet priced nothing."""
    data = _fight("Quinn", include_autos=True)
    b_ad = data["champion_stats"]["bonus_attack_damage"]
    flat = _value("Quinn", "P", "Bonus Physical Damage", 18)
    assert flat == pytest.approx(120.0)
    expected = flat + 0.40 * b_ad
    row = _on_hit_row(data)
    assert row["name"] == "Harrier (on-hit)"
    assert row["damage_per_hit"] == pytest.approx(expected, abs=0.06)
    assert row["total_damage"] == pytest.approx(expected * row["count"], abs=0.6)
    assert _parse("Riven", data)["passive"]["on_hit"]["damage_type"] == "physical"
    assert _parse("Quinn", data)["passive"]["on_hit"]["damage_type"] == "physical"
