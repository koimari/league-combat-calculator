"""E3 stack/charge/mark systems (batch 2): Ekko, Ashe, Yasuo, Yone, Rengar,
Jhin, Samira, Sett, Caitlyn, Draven, Kindred, Akshan.

One test per champion pins the stack-driven damage/empower against the
sourced values in ``data/champions.json`` via an ``/api/calculate`` fight
at level 18 (basic abilities rank 5, ultimates rank 3, no items).  Target
armor/MR are zeroed so post-mitigation damage equals the raw wiki values,
and every expected number is recomputed from the cached leveling rows plus
the fight's own champion stats — no literal expected constants.  The E3
worklist (``data/worklists/e3-mechanics.json``) lists the stack mechanics;
parse-level assertions cover the terms the fight engine cannot schedule
(Jhin's per-auto dynamic missing-health bonus is priced at the declared
missing-health ratio; Kindred's per-Mark missing-health term needs an
explicit target-missing context; Draven's Adoration is economy-only).
"""

import json
import re
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_CACHE_KEY_BY_DISPLAY = {
    str(value.get("name", "")): key
    for key, value in _CHAMPION_DATA.items()
    if isinstance(value, dict) and str(value.get("name", "")).strip()
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
LEVEL = 18


def _fight(
    champion: str,
    *,
    duration: float = 10.0,
    ranks: dict | None = None,
    autos: bool = False,
    uptime: float | None = None,
    options: dict | None = None,
    target_health: float = 2000.0,
) -> dict:
    """One /api/calculate fight at level 18, no items, zero target resists."""
    payload = {
        "champion": champion,
        "level": LEVEL,
        "items": [],
        "role": "mid",
        "ability_ranks": ranks or _FULL_RANKS,
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": autos,
        "target_health": target_health,
        "target_armor": 0,
        "target_mr": 0,
        "champion_options": options or {},
    }
    if uptime is not None:
        payload["auto_attack_uptime"] = uptime
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _leveling(
    champion: str,
    slot: str,
    attribute: str,
    *,
    description_contains: str | None = None,
) -> dict:
    """Return one leveling entry from data/champions.json, failing loudly.

    ``description_contains`` narrows to the effect whose description
    carries the phrase (Rengar W stores two "Bonus Magic Damage" arrays;
    the Ferocity one is in the "Ferocity Bonus" effect).
    """
    ability = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        if description_contains is not None and description_contains not in effect.get(
            "description", ""
        ):
            continue
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


def _resolve(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    stats: dict,
    target_max_health: float,
    *,
    level_index: bool = False,
    description_contains: str | None = None,
) -> float:
    """Sum one leveling entry at rank/level against the fight's own stats.

    ``level_index`` reads the per-level arrays (passive leveling) at the
    champion's level instead of the per-rank index.  Only the unit
    vocabularies the E3 stack mechanics use are handled; an unexpected
    unit fails loudly so the test cannot silently pass with a dropped
    term.
    """
    total = 0.0
    for modifier in _leveling(
        champion, slot, attribute, description_contains=description_contains
    ).get("modifiers", []):
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
        elif (
            unit == "% of target's missing health"
            or "of target's missing health" in unit
        ):
            total += 0.0  # run_fight parses a full-health target (missing 0)
        else:
            raise AssertionError(
                f"unhandled unit {unit!r} for {champion} {slot} {attribute}"
            )
    return total


def _api_total(row: dict, expected: float) -> None:
    """The /api/calculate serializer rounds totals to 1 decimal."""
    assert row["total_damage"] == pytest.approx(round(expected, 1), abs=0.06)


def _parse(champion: str, options: dict | None = None, target: dict | None = None):
    """Parse the champion module directly (for parse-level stack terms)."""
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


# ---------------------------------------------------------------------------
# Ekko — Z-Drive Resonance (3-stack detonation)
# ---------------------------------------------------------------------------


def test_ekko_resonance_prices_three_stack_detonations():
    """Each p_procs entry is one completed 3-stack Resonance detonation:
    level-18 flat + 80% AP (no items -> 0 AP)."""
    data = _fight("Ekko", options={"p_procs": 2})
    stats = data["champion_stats"]
    per_detonation = _resolve(
        "Ekko", "P", "Bonus Magic Damage", LEVEL, stats, 2000.0, level_index=True
    )
    row = data["breakdown"]["passive"]
    assert row["count"] == 2
    assert row["damage_per_hit"] == pytest.approx(round(per_detonation, 1), abs=0.06)
    _api_total(row, 2 * per_detonation)


# ---------------------------------------------------------------------------
# Ashe — Ranger's Focus (4-stack Focus gate)
# ---------------------------------------------------------------------------


def test_ashe_focus_stacks_gate_rangers_focus():
    """At 4 pre-stacked Focus stacks Ranger's Focus is active (flurry
    ratio 130% AD at rank 5); at 3 stacks the ability stays inactive and
    autos swing at the plain 100% AD ratio."""
    # P1-11: the 5s window keeps the fight fully in-window (the flurry
    # ratio holds for every swing; a 10s fight would mix the post-window
    # normal swings).
    active = _fight(
        "Ashe",
        ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
        autos=True,
        uptime=1.0,
        options={"q_focus_stacks": 4},
        duration=5.0,
    )
    inactive = _fight(
        "Ashe",
        ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
        autos=True,
        uptime=1.0,
        options={"q_focus_stacks": 3},
        duration=5.0,
    )
    ad = active["champion_stats"]["attack_damage"]
    flurry = (
        _leveling("Ashe", "Q", "Total Damage Per Flurry")["modifiers"][0]["values"][4]
        / 100.0
    )
    assert active["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
        ad * flurry
    )
    assert inactive["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(ad)
    # The Focus gate also withholds Q's bonus attack speed (fewer autos).
    assert (
        active["breakdown"]["auto_attacks"]["count"]
        > inactive["breakdown"]["auto_attacks"]["count"]
    )


# ---------------------------------------------------------------------------
# Yasuo — Gathering Storm (Q3) and Ride the Wind (E per-stack bonus)
# ---------------------------------------------------------------------------


def test_yasuo_e_ride_the_wind_prices_stacks():
    """E at 4 Ride the Wind stacks = base + 4 x per-stack bonus, which is
    the wiki Total Combined Damage (2x the base at rank 5)."""
    maxed = _fight("Yasuo", options={"e_stacks": 4})
    base_only = _fight("Yasuo", options={"e_stacks": 0})
    stats = maxed["champion_stats"]
    base = _resolve("Yasuo", "E", "Magic Damage", 5, stats, 2000.0)
    per_stack = _resolve("Yasuo", "E", "Bonus Damage per Stack", 5, stats, 2000.0)
    total_combined = _resolve("Yasuo", "E", "Total Combined Damage", 5, stats, 2000.0)
    assert base + 4 * per_stack == pytest.approx(total_combined)
    e_maxed = maxed["breakdown"]["E"]
    e_base = base_only["breakdown"]["E"]
    assert e_maxed["casts"] == e_base["casts"]
    _api_total(e_maxed, total_combined * e_maxed["casts"])
    _api_total(e_base, base * e_base["casts"])


def test_yasuo_q3_gathering_storm_keeps_sourced_damage():
    """At 2 Gathering Storm stacks the next Q is the Q3 whirlwind — same
    sourced damage, knock-up CC documented."""
    q3 = _fight("Yasuo", options={"q_gathering_storm": 2, "e_stacks": 0})
    plain = _fight("Yasuo", options={"q_gathering_storm": 0, "e_stacks": 0})
    stats = q3["champion_stats"]
    per_cast = _resolve("Yasuo", "Q", "Physical Damage", 5, stats, 2000.0)
    _api_total(q3["breakdown"]["Q"], per_cast * q3["breakdown"]["Q"]["casts"])
    assert q3["breakdown"]["Q"]["total_damage"] == pytest.approx(
        plain["breakdown"]["Q"]["total_damage"]
    )
    assert "Q3" in q3["breakdown"]["Q"].get("detail", "")


# ---------------------------------------------------------------------------
# Yone — Gathering Storm (Q3)
# ---------------------------------------------------------------------------


def test_yone_q3_gathering_storm_keeps_sourced_damage():
    """Yone's Q3 (2 Gathering Storm stacks) deals the same sourced damage."""
    q3 = _fight("Yone", options={"q_gathering_storm": 2})
    plain = _fight("Yone", options={"q_gathering_storm": 0})
    stats = q3["champion_stats"]
    per_cast = _resolve("Yone", "Q", "Physical Damage", 5, stats, 2000.0)
    _api_total(q3["breakdown"]["Q"], per_cast * q3["breakdown"]["Q"]["casts"])
    assert q3["breakdown"]["Q"]["total_damage"] == pytest.approx(
        plain["breakdown"]["Q"]["total_damage"]
    )
    assert "Q3" in q3["breakdown"]["Q"].get("detail", "")


# ---------------------------------------------------------------------------
# Rengar — Ferocity (4-stack empowered abilities)
# ---------------------------------------------------------------------------


def test_rengar_ferocity_empowers_q_w_e():
    """P3-3V live Ferocity: the seeded 4-stack state is consumed by the
    first basic-ability cast, and the cap-at-5th empowers the next cast
    when the fight reaches it again — the live walk prices the per-level
    Ferocity Bonus values for those casts and the base values otherwise."""
    # R's armour shred is off here: this test compares raw rows against
    # mitigated totals, and a shredded target would move the mitigation
    # rather than the row the Ferocity empowerment is about.
    empowered = _fight("Rengar", options={"p_ferocity": 4, "r_thrill_attack": False})
    base = _fight("Rengar", options={"p_ferocity": 0, "r_thrill_attack": False})
    stats = empowered["champion_stats"]

    q_emp = _resolve(
        "Rengar", "Q", "Bonus Physical Damage", LEVEL, stats, 2000.0, level_index=True
    )
    q_base = _resolve("Rengar", "Q", "Additional Physical Damage", 5, stats, 2000.0)
    assert q_emp > q_base
    # Live: the seeded-4 fight's FIRST Q consumes (empowered) and the
    # seeded-0 fight's LAST Q reaches the cap (empowered) — both Q rows
    # exceed the all-base value, and the resource ledger receipted the
    # consume at the first cast.
    assert empowered["breakdown"]["Q"]["total_damage"] > q_base * 3
    assert base["breakdown"]["Q"]["total_damage"] > q_base * 3

    _resolve(
        "Rengar",
        "W",
        "Bonus Magic Damage",
        LEVEL,
        stats,
        2000.0,
        level_index=True,
        description_contains="Ferocity Bonus",
    )
    w_base = _resolve("Rengar", "W", "Magic Damage", 5, stats, 2000.0)
    # The seed-4 fight's second W (at t=10) hits the cap and empowers.
    assert empowered["breakdown"]["W"]["total_damage"] > w_base * 2
    assert base["breakdown"]["W"]["total_damage"] == pytest.approx(
        w_base * base["breakdown"]["W"]["casts"], abs=0.06
    )

    e_emp = _resolve(
        "Rengar", "E", "Bonus Physical Damage", LEVEL, stats, 2000.0, level_index=True
    )
    e_base = _resolve("Rengar", "E", "Physical Damage", 5, stats, 2000.0)
    assert e_emp > e_base
    assert empowered["breakdown"]["E"]["total_damage"] == pytest.approx(
        e_base * empowered["breakdown"]["E"]["casts"], abs=0.06
    )
    assert base["breakdown"]["E"]["total_damage"] == pytest.approx(
        e_base * base["breakdown"]["E"]["casts"], abs=0.06
    )


# ---------------------------------------------------------------------------
# Jhin — Whisper 4th shot (4-round clip)
# ---------------------------------------------------------------------------


def test_jhin_fourth_shot_prices_missing_health_bonus():
    """Pre-stacked to the final round (p_shot_number=4), each final round
    adds 25% (level 18) of target max health at the declared missing-health
    ratio; the fight's auto stream determines how many final rounds land."""
    data = _fight(
        "Jhin",
        autos=True,
        uptime=1.0,
        options={"p_shot_number": 4, "p_missing_health": 1.0},
    )
    row = data["breakdown"]["final_round"]
    per_round = 0.25 * data["target_effective_max_health"]
    assert (
        row["count"] == 2
    )  # 6 autos at 0.625 AS over 10s: final rounds on autos 1 and 5
    assert row["damage_per_hit"] == pytest.approx(round(per_round, 1), abs=0.06)
    _api_total(row, 2 * per_round)


def test_jhin_fourth_shot_parse_formula_matches_wiki():
    """Parse-level: the final-round part is the sourced 25% missing-health
    bonus at level 18 (15/20/25% at levels 1/6/11), not the Every Moment
    Matters AD percent."""
    _stats, abilities = _parse(
        "Jhin",
        options={"p_shot_number": 4},
        target={
            "target_max_health": 2000.0,
            "target_current_health": 1000.0,
            "target_missing_health": 1000.0,
        },
    )
    part = abilities["passive"]["parts"][0]
    assert part.hp_scaled_damage(1.0) == pytest.approx(0.25 * 2000.0)
    assert part.hp_scaled_damage(0.5) == pytest.approx(0.25 * 1000.0)


# ---------------------------------------------------------------------------
# Samira — Style (6-stack S rank)
# ---------------------------------------------------------------------------


def test_samira_style_unlocks_inferno_trigger():
    """At 6 Style stacks (S rank) Inferno Trigger is available and consumes
    the stacks; its sourced 10-shot packet damage is unchanged."""
    data = _fight("Samira", options={"p_style_stacks": 6})
    stats = data["champion_stats"]
    per_shot = _resolve("Samira", "R", "Physical Damage Per Shot", 3, stats, 2000.0)
    row = data["breakdown"]["R"]
    _api_total(row, per_shot * 10 * row["casts"])
    assert "S rank" in row.get("detail", "")
    _, abilities = _parse("Samira", options={"p_style_stacks": 6})
    assert "6/6" in abilities["passive"]["detail"]
    _, abilities_0 = _parse("Samira", options={"p_style_stacks": 0})
    assert "0/6" in abilities_0["passive"]["detail"]


# ---------------------------------------------------------------------------
# Sett — Pit Grit right-punch combo
# ---------------------------------------------------------------------------


def test_sett_right_punch_prices_combo_bonus():
    """Each Right Punch (the combo's empowered hit) deals the sourced
    5 : 100 by level (+ 55% bonus AD) bonus physical damage."""
    data = _fight("Sett", options={"p_right_punches": 3})
    stats = data["champion_stats"]
    flat = _leveling("Sett", "P", "Per-Level Scaling")["modifiers"][0]["values"][
        LEVEL - 1
    ]
    per_punch = flat + 0.55 * stats["bonus_attack_damage"]
    row = data["breakdown"]["passive"]
    assert row["count"] == 3
    assert row["damage_per_hit"] == pytest.approx(round(per_punch, 1), abs=0.06)
    _api_total(row, 3 * per_punch)


# ---------------------------------------------------------------------------
# Caitlyn — Headshot (5-stack Count)
# ---------------------------------------------------------------------------


def test_caitlyn_pre_stacked_headshot_advances_cadence():
    """Pre-stacked Count stacks advance the headshot cadence: with 4
    pre-stacks the first auto is already a Headshot, so an 11-auto fight
    lands 2 cadence headshots instead of 1."""
    pre = _fight(
        "Caitlyn",
        ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
        autos=True,
        uptime=1.0,
        options={"p_pre_stacks": 4},
    )
    plain = _fight(
        "Caitlyn",
        ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
        autos=True,
        uptime=1.0,
        options={"p_pre_stacks": 0},
    )
    assert pre["breakdown"]["auto_attacks"]["count"] == 11
    assert "2 cadence" in pre["breakdown"]["passive"]["detail"]
    assert "1 cadence" in plain["breakdown"]["passive"]["detail"]
    # Headshot rider at level 18 (100% AD ratio, 0 crit).  With an auto
    # stream the converted autos already swing in the auto_attacks row, so
    # the passive row prices the rider only.
    ad = pre["champion_stats"]["attack_damage"]
    assert pre["breakdown"]["passive"]["total_damage"] == pytest.approx(2 * ad)
    assert plain["breakdown"]["passive"]["total_damage"] == pytest.approx(ad)


# ---------------------------------------------------------------------------
# Draven — Adoration (economy stacks)
# ---------------------------------------------------------------------------


def test_draven_adoration_is_explicit_economy_state():
    """Adoration is a gold economy: a champion kill cashes in
    25 + 2 x stacks bonus gold and never contributes damage."""
    _, abilities = _parse(
        "Draven", options={"adoration_stacks": 100, "adoration_cash_in": True}
    )
    detail = abilities["passive"]["detail"]
    assert "100 Adoration" in detail
    assert "225 bonus gold" in detail
    with_adoration = _fight(
        "Draven", options={"adoration_stacks": 100, "adoration_cash_in": True}
    )
    without = _fight("Draven", options={"adoration_stacks": 0})
    assert with_adoration["total_damage"] == pytest.approx(without["total_damage"])


# ---------------------------------------------------------------------------
# Kindred — Mounting Dread (3-stack Wolf pounce) + marks
# ---------------------------------------------------------------------------


def test_kindred_mounting_dread_pounces_on_third_stack():
    """At 3 Mounting Dread stacks Wolf pounces: the sourced Additional
    Physical Damage (+ 100% bonus AD + missing-health term).  In the fight
    the target parses at full health, so the flat+AD portion is priced."""
    data = _fight("Kindred", options={"marks": 4, "e_stacks": 3})
    stats = data["champion_stats"]
    per_pounce = _resolve(
        "Kindred", "E", "Additional Physical Damage", 5, stats, 2000.0
    )
    row = data["breakdown"]["E"]
    _api_total(row, per_pounce * row["casts"])


def test_kindred_marks_scale_e_missing_health_term():
    """Parse-level: E's missing-health term is 5% (+ 0.5% per Mark); at 4
    marks and 500 missing health the pounce gains 7% of 500 = 35."""
    stats, abilities = _parse(
        "Kindred",
        options={"marks": 4, "e_stacks": 3},
        target={
            "target_max_health": 2000.0,
            "target_current_health": 1500.0,
            "target_missing_health": 500.0,
        },
    )
    per_pounce = _resolve(
        "Kindred", "E", "Additional Physical Damage", 5, stats, 2000.0
    )
    assert abilities["E"]["total_raw"] == pytest.approx(per_pounce + 0.07 * 500.0)


# ---------------------------------------------------------------------------
# Akshan — Dirty Fighting (3-stack proc)
# ---------------------------------------------------------------------------


def test_akshan_dirty_fighting_prices_three_stack_proc():
    """Each passive_procs entry is one completed 3-stack Dirty Fighting
    detonation: 150 (+ 60% AP) at level 18; the proc lands on the third
    damaging attack (auto_stack_every=3)."""
    data = _fight("Akshan", autos=True, uptime=1.0, options={"passive_procs": 1})
    stats = data["champion_stats"]
    per_proc = 150.0 + 0.60 * stats["ability_power"]
    row = data["breakdown"]["passive"]
    assert row["count"] == 1
    assert row["damage_per_hit"] == pytest.approx(round(per_proc, 1), abs=0.06)
    _api_total(row, per_proc)
