"""E9.5 gap-fix wave (E9-3) — final genuine audit gaps, 10 champions.

One test (or two) per champion pins the corrected sourced formula against
the cached ``data/champions.json`` leveling rows via an ``/api/calculate``
fight at level 18 (basic abilities rank 5, ultimates rank 3, no items, 0
target resists) plus parse-level assertions where the fight engine cannot
schedule the term (Viego R's live missing-health part, Shyvana's heal
formula).  Every expected number is recomputed from the cached leveling
rows plus the fight's own champion stats — no invented constants, and the
``_resolve`` helper fails loudly on an unexpected unit so a dropped term
cannot pass silently.
"""

import json
import re
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.champions.slotlib import find_named_leveling

LEVEL = 18
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_CACHE_KEY_BY_DISPLAY = {
    str(value.get("name", "")): key
    for key, value in _CHAMPION_DATA.items()
    if isinstance(value, dict) and str(value.get("name", "")).strip()
}


def _leveling(champion: str, slot: str, attribute: str, occurrence: int = 0) -> dict:
    """Return one leveling entry from data/champions.json, failing loudly."""
    ability = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    leveling = find_named_leveling(ability, attribute, occurrence=occurrence)
    if leveling is None:
        raise AssertionError(
            f"no {attribute!r} leveling row (occurrence {occurrence}) for {champion} {slot}"
        )
    return leveling


def _leveling_at(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    stats: dict,
    target_max_health: float,
    *,
    level_index: bool = False,
    occurrence: int = 0,
    unit_override: dict[str, str] | None = None,
) -> float:
    """Sum one leveling entry at rank/level against the fight's own stats.

    ``level_index`` reads per-level arrays at the champion's level instead
    of the per-rank index.  Only the unit vocabularies the E9-3 formulas
    use are handled; an unexpected unit fails loudly.
    """
    total = 0.0
    for modifier in _leveling(champion, slot, attribute, occurrence).get(
        "modifiers", []
    ):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = (
            min(LEVEL - 1, len(values) - 1)
            if level_index
            else min(rank - 1, len(values) - 1)
        )
        value = float(values[idx])
        unit = re.sub(r"\s+", " ", str(units[idx]).strip()) if idx < len(units) else ""
        unit = unit_override.get(unit, unit) if unit_override else unit
        if unit in ("", "%"):
            total += value
        elif unit.startswith(
            "% :"
        ):  # Shyvana W Heal: "% : 8.47% (based on level" prose
            total += 0.0
        elif unit == "% AP":
            total += value / 100.0 * float(stats.get("ability_power", 0.0))
        elif unit == "% AD":
            total += value / 100.0 * float(stats.get("attack_damage", 0.0))
        elif unit == "% bonus AD":
            total += value / 100.0 * float(stats.get("bonus_attack_damage", 0.0))
        elif unit == "% of target's maximum health":
            total += value / 100.0 * target_max_health
        elif unit == "% of her maximum health":
            total += value / 100.0 * float(stats.get("health", 0.0))
        elif (
            unit == "% of target's missing health"
            or "of target's missing health" in unit
        ):
            total += 0.0  # full-health parse context (missing 0)
        elif "of expended Grit" in unit:
            total += value / 100.0 * 0.0  # grit term priced by the option
        elif "per 100 AD" in unit:
            total += (
                value
                / 100.0
                * float(stats.get("attack_damage", 0.0))
                / 100.0
                * target_max_health
            )
        else:
            raise AssertionError(
                f"unhandled unit {unit!r} for {champion} {slot} {attribute}"
            )
    return total


def _api_total(row: dict, expected: float) -> None:
    """The /api/calculate serializer rounds totals to 1 decimal."""
    assert row["total_damage"] == pytest.approx(round(expected, 1), abs=0.06)


def _parse(champion: str, options: dict | None = None, target: dict | None = None):
    """Parse the champion module directly (for parse-level assertions)."""
    data = get_champion(champion)
    stats = calculate_total_stats(data, LEVEL, [])
    return stats, parse_champion_abilities(
        data,
        LEVEL,
        stats["ability_power"],
        ability_ranks=_FULL_RANKS,
        champion_stats=stats,
        target_stats=target
        or {
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=options or None,
    )


def _fight(
    champion: str,
    *,
    duration: float = 6.0,
    options: dict | None = None,
    enemy: str | None = None,
    target_health: float = 2000.0,
    target_armor: float = 0.0,
    target_mr: float = 0.0,
) -> dict:
    """One /api/calculate fight at level 18, no items, 0 target resists."""
    payload = {
        "champion": champion,
        "level": LEVEL,
        "items": [],
        "ability_ranks": dict(_FULL_RANKS),
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "target_health": target_health,
        "target_armor": target_armor,
        "target_mr": target_mr,
    }
    if options:
        payload["champion_options"] = options
    if enemy:
        payload["enemies"] = [{"champion": enemy, "level": LEVEL, "items": []}]
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


# ---------------------------------------------------------------------------
# Shyvana — W self-shield (E8c payload) + dragon-form recast heal
# ---------------------------------------------------------------------------


def test_shyvana_w_carries_the_sourced_self_shield():
    """W's shield = 'Shield Strength' 60-140 by rank + 12% bonus health,
    plus the 'Increased shield per champion' 18-42 by rank + 3.6% bonus
    health per nearby enemy champion (1 in a 1v1 duel)."""
    stats, abilities = _parse("Shyvana")
    (shield,) = abilities["W"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(140.0 + 42.0)  # rank 5, no items
    assert shield["duration"] == pytest.approx(1.0)  # consumed at the recast
    assert shield["source"] == "Inferno Aegis"
    _, abilities_zero = _parse("Shyvana", options={"w_nearby_champions": 0})
    (shield_zero,) = abilities_zero["W"]["self_shield_events"]
    assert shield_zero["amount"] == pytest.approx(140.0)


def test_shyvana_dragon_recast_heals_from_missing_health():
    """Dragon-form W recast heal: 60 : 104.71 (based on level) + 4% :
    8.47% (based on level) of missing health, when the explosion hits a
    champion — a live amount_formula keyed on the W damage event."""
    combat = _fight("Shyvana", options={"dragon_form": True}, enemy="Aatrox")["combat"]
    heals = [
        event
        for event in combat["healing_events"]
        if event.get("attacker") == "main" and event.get("source") == "Inferno Aegis"
    ]
    assert len(heals) == 1
    flat = _leveling_at("Shyvana", "W", "Heal", 1, {}, 0.0, level_index=True)
    missing_pct = _leveling_at(
        "Shyvana", "W", "Missing Health Damage", 1, {}, 0.0, level_index=True
    )
    # The 20-value "based on level" arrays span levels 1-20: level 18
    # indexes values[17] == 100.0 flat and 8.0% missing health.
    assert flat == pytest.approx(100.0)
    assert missing_pct == pytest.approx(8.0)
    # By the +1s recast the fight has damaged Shyvana, so the live formula
    # pays strictly more than the flat floor.
    assert heals[0]["applied_amount"] > flat
    assert heals[0]["applied_amount"] <= flat + missing_pct / 100.0 * 2000.0


def test_shyvana_human_form_does_not_heal_and_scanner_defers():
    """The W heal is dragon-form-only; human-form W still shields.  The
    support scanner defers Shyvana's W (module-authored shield payload +
    healing rule), so no scanner-derived 'Inferno Aegis · Heal' or
    '· Shield Strength' rows appear."""
    combat = _fight("Shyvana", enemy="Aatrox")["combat"]
    main_heals = [
        event
        for event in combat["healing_events"]
        if event.get("attacker") == "main" and event.get("source") == "Inferno Aegis"
    ]
    assert main_heals == []
    supports = combat["support_events"]
    assert not any("· Heal" in str(event.get("source", "")) for event in supports)
    assert not any(
        "· Shield Strength" in str(event.get("source", "")) for event in supports
    )
    shields = [e for e in supports if e.get("kind") == "shield"]
    assert len(shields) == 1
    assert shields[0]["amount"] == pytest.approx(182.0)
    assert shields[0]["duration"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Sejuani — Winter's Wrath both flail swings
# ---------------------------------------------------------------------------


def test_sejuani_w_prices_both_flail_swings():
    """W total = first swing (5-45 + 30% AP + 4% max HP) + second swing
    (5-85 + 60% AP + 8% max HP) == the cached Total Physical Damage row
    (10-130 + 90% AP + 12% of Sejuani's maximum health)."""
    stats, abilities = _parse("Sejuani")
    first = _leveling_at(
        "Sejuani", "W", "Physical Damage", 5, stats, 2000.0, occurrence=0
    )
    second = _leveling_at(
        "Sejuani", "W", "Physical Damage", 5, stats, 2000.0, occurrence=1
    )
    total = _leveling_at("Sejuani", "W", "Total Physical Damage", 5, stats, 2000.0)
    assert first == pytest.approx(45.0 + 0.04 * stats["health"])
    assert second == pytest.approx(85.0 + 0.08 * stats["health"])
    assert abilities["W"]["total_raw"] == pytest.approx(first + second)
    assert total == pytest.approx(first + second)
    assert abilities["W"]["total_raw"] == pytest.approx(438.16)
    # The fight prices both swings per cast (2 casts in the 6s window).
    data = _fight("Sejuani")
    _api_total(
        data["breakdown"]["W"], (first + second) * data["breakdown"]["W"]["casts"]
    )


# ---------------------------------------------------------------------------
# Sivir — two-way Boomerang Blade
# ---------------------------------------------------------------------------


def test_sivir_q_prices_the_two_way_boomerang():
    """Q = the cached Total Maximum Champion Damage row (120-320 + 140%
    bonus AD + 120% AP == 2 x the single-pass row): the blade deals the
    same damage on the way out and back."""
    stats, abilities = _parse("Sivir")
    total = _leveling_at(
        "Sivir", "Q", "Total Maximum Champion Damage", 5, stats, 2000.0
    )
    single = _leveling_at("Sivir", "Q", "Physical Damage", 5, stats, 2000.0)
    assert total == pytest.approx(2 * single)
    assert total == pytest.approx(320.0)  # rank 5, no items, 0 AP
    assert abilities["Q"]["total_raw"] == pytest.approx(total)
    data = _fight("Sivir")
    _api_total(data["breakdown"]["Q"], total * data["breakdown"]["Q"]["casts"])


# ---------------------------------------------------------------------------
# Xerath — Rite of the Arcane all recasts + Arcane Perfection stacks
# ---------------------------------------------------------------------------


def test_xerath_r_prices_every_barrage():
    """R = 'Number of Recasts' (4/5/6) x per-shot 'Magic Damage' == the
    cached 'Total Magic Damage' row (680/1100/1620)."""
    stats, abilities = _parse("Xerath")
    recasts = _leveling_at("Xerath", "R", "Number of Recasts", 3, stats, 2000.0)
    per_shot = _leveling_at("Xerath", "R", "Magic Damage", 3, stats, 2000.0)
    total = _leveling_at("Xerath", "R", "Total Magic Damage", 3, stats, 2000.0)
    assert recasts == pytest.approx(6.0)
    assert total == pytest.approx(per_shot * recasts)
    assert total == pytest.approx(1620.0)
    assert abilities["R"]["total_raw"] == pytest.approx(total)
    data = _fight("Xerath")
    _api_total(data["breakdown"]["R"], total * data["breakdown"]["R"]["casts"])


def test_xerath_r_arcane_perfection_stacks_bonus():
    """Each barrage beyond the first carries the 'Increased Damage per
    Stack' bonus (capped at 'Maximum Stacks' 3/4/5): with 5 stacks at rank
    3 the six barrages deal 270/300/330/360/390/420 == 2070."""
    stats, abilities = _parse("Xerath", options={"r_arcane_perfection": 5})
    recasts = int(
        round(_leveling_at("Xerath", "R", "Number of Recasts", 3, stats, 2000.0))
    )
    per_shot = _leveling_at("Xerath", "R", "Magic Damage", 3, stats, 2000.0)
    per_stack = _leveling_at(
        "Xerath", "R", "Increased Damage per Stack", 3, stats, 2000.0
    )
    maximum = int(
        round(_leveling_at("Xerath", "R", "Maximum Stacks", 3, stats, 2000.0))
    )
    expected = sum(
        per_shot + min(index, 5, maximum) * per_stack for index in range(recasts)
    )
    assert expected == pytest.approx(2070.0)
    assert abilities["R"]["total_raw"] == pytest.approx(expected)
    data = _fight("Xerath", options={"r_arcane_perfection": 5})
    _api_total(data["breakdown"]["R"], expected * data["breakdown"]["R"]["casts"])


# ---------------------------------------------------------------------------
# Viego — Q active + second strike; R base strike + missing-health bonus
# ---------------------------------------------------------------------------


def test_viego_q_prices_the_active_thrust():
    """Q prices the active 'Physical Damage' row (25-85 + 70% AD); the
    mark-consuming second strike (20% AD + 15% AP prose) is option-gated."""
    stats, abilities = _parse("Viego")
    active = _leveling_at("Viego", "Q", "Physical Damage", 5, stats, 2000.0)
    assert active == pytest.approx(85.0 + 0.7 * stats["attack_damage"])
    assert abilities["Q"]["total_raw"] == pytest.approx(active)
    # The %current-health on-hit rides every auto (engine current-health
    # on-hit simulation with the 10-30 minimum floor).
    on_hit = abilities["Q"]["on_hit"]
    assert on_hit["current_health_percent"] == pytest.approx(
        _leveling("Viego", "Q", "Bonus Physical Damage")["modifiers"][0]["values"][4]
    )
    assert on_hit["min_damage"] == pytest.approx(
        _leveling("Viego", "Q", "Minimum Bonus Damage")["modifiers"][0]["values"][4]
    )
    stats2, abilities2 = _parse("Viego", options={"q_second_strike": 2})
    bonus = 2 * (0.20 * stats2["attack_damage"] + 0.15 * stats2["ability_power"])
    assert abilities2["Q"]["total_raw"] == pytest.approx(active + bonus)
    data = _fight("Viego")
    _api_total(data["breakdown"]["Q"], active * data["breakdown"]["Q"]["casts"])


def test_viego_r_prices_base_strike_plus_missing_health():
    """R = the 120% AD base strike (prose) plus the %missing-health bonus
    ('Physical Damage' row 12/16/20% + 5% per 100 bonus AD) as a live
    hp-scaled part evaluated at the strike."""
    stats, abilities = _parse("Viego")
    part_base, part_missing = abilities["R"]["parts"]
    assert part_base.amount == pytest.approx(1.20 * stats["attack_damage"])
    assert part_missing.hp_scaled_damage(1.0) == pytest.approx(0.20 * 2000.0)
    assert part_missing.hp_scaled_damage(0.5) == pytest.approx(0.20 * 1000.0)
    data = _fight("Viego")
    # The base strike is the deterministic floor of the R row (the
    # missing-health part only adds more as the target takes damage).
    assert data["breakdown"]["R"]["total_damage"] >= 1.20 * stats["attack_damage"] - 0.1


# ---------------------------------------------------------------------------
# Sett — Q both empowered attacks; W true damage + grit + shield
# ---------------------------------------------------------------------------


def test_sett_q_prices_both_empowered_attacks():
    """Q = the 'Total Bonus Physical Damage' row (20-100 by rank) plus the
    %max-HP term: the cached base percentage (2% for the total row) plus
    the rank-scaled per-100-AD percentage embedded in the unit string
    (2/3/4/5/6% by rank), against the target's max health."""
    stats, abilities = _parse("Sett")
    row = _leveling("Sett", "Q", "Total Bonus Physical Damage")
    flat = row["modifiers"][0]["values"][4]
    base_pct = row["modifiers"][1]["values"][4]  # 2 (cached constant)
    per_100 = float(re.findall(r"\d+(?:\.\d+)?", row["modifiers"][1]["units"][4])[4])
    expected = (
        flat
        + (base_pct / 100.0 + per_100 / 100.0 * stats["attack_damage"] / 100.0) * 2000.0
    )
    assert expected == pytest.approx(293.6)
    assert abilities["Q"]["total_raw"] == pytest.approx(expected)
    data = _fight("Sett")
    _api_total(data["breakdown"]["Q"], expected * data["breakdown"]["Q"]["casts"])


def test_sett_w_true_damage_grit_and_shield():
    """W (Haymaker) = center-line TRUE damage: the 'Damage' row flat
    (80-160) + 25% (+ 25% per 100 bonus AD) of the expended Grit
    (w_grit option), and the expended Grit shields Sett for 3s."""
    _, abilities = _parse("Sett", options={"w_grit": 1000})
    w = abilities["W"]
    assert w["damage_type"] == "true"
    assert w["total_raw"] == pytest.approx(160.0 + 0.25 * 1000.0)  # 0 bAD
    (shield,) = w["self_shield_events"]
    assert shield["amount"] == pytest.approx(1000.0)
    assert shield["duration"] == pytest.approx(3.0)
    data = _fight("Sett", options={"w_grit": 1000})
    _api_total(data["breakdown"]["W"], 410.0 * data["breakdown"]["W"]["casts"])


# ---------------------------------------------------------------------------
# Poppy — Keeper's Verdict charged branch
# ---------------------------------------------------------------------------


def test_poppy_r_charged_branch():
    """R defaults to the uncharged 'Physical Damage' row (100-200 + 45%
    bonus AD); r_charged prices the fully-charged 'Increased Damage' row
    (200-400 + 90% bonus AD == 2x)."""
    stats, abilities = _parse("Poppy")
    uncharged = _leveling_at("Poppy", "R", "Physical Damage", 3, stats, 2000.0)
    charged = _leveling_at("Poppy", "R", "Increased Damage", 3, stats, 2000.0)
    assert charged == pytest.approx(2 * uncharged)
    assert abilities["R"]["total_raw"] == pytest.approx(uncharged)
    assert uncharged == pytest.approx(200.0)
    _, abilities_charged = _parse("Poppy", options={"r_charged": True})
    assert abilities_charged["R"]["total_raw"] == pytest.approx(charged)
    assert charged == pytest.approx(400.0)
    data = _fight("Poppy")
    _api_total(data["breakdown"]["R"], uncharged * data["breakdown"]["R"]["casts"])
    data_charged = _fight("Poppy", options={"r_charged": True})
    _api_total(
        data_charged["breakdown"]["R"],
        charged * data_charged["breakdown"]["R"]["casts"],
    )


# ---------------------------------------------------------------------------
# Yone — Soul Unbound stored true damage
# ---------------------------------------------------------------------------


def test_yone_e_prices_the_stored_damage():
    """Yone prices W/R mixed packets and stores the exact Spirit Form window."""
    stats, abilities = _parse("Yone")
    ratio = _leveling("Yone", "E", "Damage Stored")["modifiers"][0]["values"][4] / 100.0
    w_physical = _leveling_at("Yone", "W", "Physical Damage", 5, stats, 2000.0)
    w_magic = _leveling_at("Yone", "W", "Magic Damage", 5, stats, 2000.0)
    r_physical = _leveling_at("Yone", "R", "Physical Damage", 3, stats, 2000.0)
    r_magic = _leveling_at("Yone", "R", "Magic Damage", 3, stats, 2000.0)
    assert ratio == pytest.approx(0.35)
    assert abilities["W"]["damage_type"] == "mixed"
    assert abilities["W"]["total_raw"] == pytest.approx(w_physical + w_magic)
    assert abilities["R"]["damage_type"] == "mixed"
    assert abilities["R"]["total_raw"] == pytest.approx(r_physical + r_magic)
    assert abilities["E"]["total_raw"] == pytest.approx(0.0)
    assert abilities["E"]["stored_damage"]["ratio"] == pytest.approx(ratio)
    assert abilities["E"]["damage_type"] == "true"
    data = _fight("Yone")
    e_start = next(
        event["time"] for event in data["cast_timeline"] if event["slot"] == "E"
    )
    e_recast = next(
        event
        for event in data["damage_events"]
        if event["source"] == "E" and event["damage_type"] == "true"
    )
    stored_sources = [
        event
        for event in data["damage_events"]
        if event["source"] in {"Q", "W", "R", "auto_attacks"}
        and event["damage_type"] in {"physical", "magic"}
        and e_start <= event["time"] <= e_recast["time"]
    ]
    assert stored_sources
    assert e_recast["time"] == pytest.approx(e_start + 5.0)
    _api_total(
        data["breakdown"]["E"], ratio * sum(event["damage"] for event in stored_sources)
    )
    _api_total(
        data["breakdown"]["W"], (w_physical + w_magic) * data["breakdown"]["W"]["casts"]
    )
    _api_total(
        data["breakdown"]["R"], (r_physical + r_magic) * data["breakdown"]["R"]["casts"]
    )

    resisted = _fight("Yone", target_armor=100.0, target_mr=100.0)
    _api_total(
        resisted["breakdown"]["R"],
        r_physical * 0.5 + r_magic * 0.5,
    )


# ---------------------------------------------------------------------------
# Vel'Koz — Life Form Disintegration Ray full channel
# ---------------------------------------------------------------------------


def test_velkoz_r_prices_the_full_13_tick_channel():
    """R = 13 x 'Damage Per Tick' == the 'Maximum Damage' row
    (450/700/925) at the sourced 0.2-second cadence over the 2.6s
    channel (the E2 per-tick x count pattern)."""
    stats, abilities = _parse("Vel'Koz")
    per_tick = _leveling_at("Vel'Koz", "R", "Damage Per Tick", 3, stats, 2000.0)
    maximum = _leveling_at("Vel'Koz", "R", "Maximum Damage", 3, stats, 2000.0)
    assert maximum == pytest.approx(13 * per_tick, abs=0.1)
    assert maximum == pytest.approx(925.0)
    assert abilities["R"]["total_raw"] == pytest.approx(13 * per_tick)
    assert abilities["R"]["dot_duration"] == pytest.approx(2.6)
    data = _fight("Vel'Koz")
    # 13 x 71.15 == 924.95 (the wiki's Maximum Damage row rounds to 925);
    # compare the unrounded sourced product against the serialized row.
    assert data["breakdown"]["R"]["total_damage"] == pytest.approx(
        13 * per_tick * data["breakdown"]["R"]["casts"], abs=0.06
    )


# ---------------------------------------------------------------------------
# Rammus — Defensive Ball Curl thorns formula
# ---------------------------------------------------------------------------


def test_rammus_w_prices_the_thorns_formula():
    """W = 15 + 10% total armor + 10% total magic resistance magic damage
    per enemy basic attack during the stance (cached description prose;
    there is no leveling row), priced per w_thorns_autos."""
    stats, abilities = _parse("Rammus", options={"w_thorns_autos": 6})
    per_auto = 15.0 + 0.10 * stats["armor"] + 0.10 * stats["magic_resistance"]
    assert abilities["W"]["total_raw"] == pytest.approx(6 * per_auto)
    assert abilities["W"]["damage_type"] == "magic"
    data = _fight("Rammus", options={"w_thorns_autos": 6})
    _api_total(data["breakdown"]["W"], 6 * per_auto * data["breakdown"]["W"]["casts"])
    _, abilities_zero = _parse("Rammus")
    assert abilities_zero["W"]["total_raw"] == pytest.approx(0.0)
