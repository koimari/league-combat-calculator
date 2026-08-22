"""P1 — zero-review closures for ten champions (batch-p1-1).

One test per champion pins the closed mechanic against values traced to
``data/champions.json`` leveling rows / description prose and the fight's
own stats in a ``/api/calculate`` fight at level 18, ranks Q5/W5/E5/R3,
no items, target armor/MR 0 (the pair engine prices against the enemy's
own resistances — the fight's own stats — so expectations apply the
sourced 100/(100 + resist) mitigation):

- Akshan   — Dirty Fighting 3-stack proc SHIELD (40:280 by level + 35%
  bonus AD for 2s, cached P "Bonus Damage" row) rides the proc entry as a
  self_shield_events payload; one shield per proc burst (the 16/12/8/4s
  internal cooldown cannot elapse between cast-boundary procs).
- KSante   — All Out's 20% omnivamp (cached R prose) is granted as a
  stat_buff and prices the engine's explicitly single-target attack
  packets (20% of their post-mitigation damage).
- Locke    — W Soul Ignition's recast heal via the E8a grey-health
  primitive: 100% of post-mitigation champion damage taken during the 6s
  active is stored (capped by the "Damage taken grey health cap" row) and
  healed at the automatic 6s recast.
- Malphite — W prices BOTH empowered-attack parts (Additional Physical
  Damage on-hit + cone Physical Damage, single target) and grants the
  tripled bonus armor ("Increased Bonus Armor" row) as a BUFF-phase stat
  that feeds E's 40% armor ratio.
- Nasus    — P Soul Eater lifesteal rule (HEALING_RULE_CHAMPIONS):
  12/18/24% by level (game-file breakpoints 7/13) of post-mitigation
  physical basic-attack/on-hit damage.
- RekSai   — E max-Fury branch via the e_fury option: at 100 Fury the
  sourced True Damage row (84-204 + 72% bonus AD == 120% of the physical
  row) is priced as true damage.
- Seraphine — Q prices the 0%:75% missing-health amplifier as an
  hp-scaled part (== the "Maximum Enhanced Damage" row at full missing).
- Sylas    — the CP-era E2 shield atom is documented as HISTORICAL
  (removed V10.2 per the wiki patch history; the pinned cache has no
  shield row) — the E packet is complete.
- Vex      — P Gloom detonation priced as an on-hit rider (40:162.94 by
  level + 25% AP, cached "Bonus Magic Damage" row) capped at the
  p_gloom_detonations option.
- Yasuo    — P Intent crit conversion engine hook: total crit chance
  doubled, crits deal 90% of the normal crit damage (champion stat
  criticalStrikeDamageModifier), excess crit converts to bonus AD; Steel
  Tempest splits the flat base (never crits) from the crit-eligible 105%
  AD portion.
"""

import pytest

from src.app import app
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.slotlib import extract_named
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(
    champion: str,
    *,
    level: int = 18,
    ranks: dict | None = None,
    options: dict | None = None,
    items: list[str] | None = None,
    enemy: str = "Aatrox",
    duration: float = 6.0,
    target_health: float = 3000.0,
) -> dict:
    payload = {
        "champion": champion,
        "level": level,
        "items": items or [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "ability_ranks": ranks or dict(RANKS),
        "enemies": [{"champion": enemy, "level": 18, "items": []}],
        "target_health": target_health,
        "target_armor": 0,
        "target_mr": 0,
    }
    if options is not None:
        payload["champion_options"] = options
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _main_breakdown(combat: dict) -> dict:
    return next(row for row in combat["breakdown"] if row["participant_id"] == "main")


def _main_survival(combat: dict) -> dict:
    return next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )["survival"]


def _enemy_stats(combat: dict) -> dict:
    return next(
        row["stats"]
        for row in combat["participants"]
        if row["participant_id"].startswith("enemy")
    )


def _main_damage_events(combat: dict, source: str) -> list[dict]:
    return [
        e
        for e in combat.get("events", [])
        if e.get("attacker") == "main" and e.get("source") == source
    ]


def _main_heals(combat: dict, source: str) -> list[dict]:
    return [
        e
        for e in combat.get("healing_events", [])
        if e.get("attacker") == "main" and e.get("source") == source
    ]


def _shield_rows(combat: dict, *, source_startswith: str) -> list[dict]:
    return [
        e
        for e in combat.get("support_events", [])
        if e.get("kind") == "shield"
        and str(e.get("source", "")).startswith(source_startswith)
    ]


def _parse(champion: str, *, level: int = 18, stats=None, options=None, ranks=None):
    data = get_champion(champion)
    if stats is None:
        stats = calculate_total_stats(data, level, [])
    abilities = parse_champion_abilities(
        data,
        level,
        stats.get("ability_power", 0.0),
        ability_ranks=ranks or dict(RANKS),
        champion_stats=stats,
        champion_options=options,
        target_stats={
            "target_max_health": 3000.0,
            "target_current_health": 3000.0,
            "target_missing_health": 0.0,
        },
    )
    return data, stats, abilities


def _mitigated(raw: float, damage_type: str, enemy_stats: dict) -> float:
    resist = (
        enemy_stats["armor"]
        if damage_type == "physical"
        else enemy_stats["magic_resistance"]
    )
    return raw * 100.0 / (100.0 + resist)


# ---------------------------------------------------------------------------
# Akshan — Dirty Fighting 3-stack proc shield
# ---------------------------------------------------------------------------


def test_akshan_proc_shield_payload_is_sourced():
    data, stats, abilities = _parse("Akshan")
    (shield,) = abilities["passive"]["self_shield_events"]
    passive = data["abilities"]["P"][0]
    expected = extract_named(passive, "Bonus Damage", 18, stats, {})
    assert shield["amount"] == pytest.approx(expected)
    assert shield["amount"] == pytest.approx(280.0)  # L18 flat, 0 bonus AD
    assert shield["duration"] == pytest.approx(2.0)
    assert shield["source"] == "Dirty Fighting (3-Stack Shield)"


def test_akshan_api_proc_shield_absorbs_sourced_amount():
    combat = _fight("Akshan")
    rows = _shield_rows(combat, source_startswith="Dirty Fighting (3-Stack")
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(280.0)
    assert rows[0]["duration"] == pytest.approx(2.0)
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(280.0)


def test_akshan_zero_procs_emit_no_shield():
    combat = _fight("Akshan", options={"passive_procs": 0})
    assert not _shield_rows(combat, source_startswith="Dirty Fighting (3-Stack")
    assert _main_survival(combat)["support_shield_received"] == 0.0


# ---------------------------------------------------------------------------
# K'Sante — All Out 20% omnivamp
# ---------------------------------------------------------------------------


def _omnivamp_heals(combat):
    return [
        h
        for h in combat.get("healing_events", [])
        if h.get("attacker") == "main" and h.get("source", "").startswith("Omnivamp")
    ]


def test_ksante_all_out_omnivamp_heals_twenty_percent_of_attack_packets():
    combat = _fight("KSante", options={"all_out": True})
    heals = _omnivamp_heals(combat)
    assert heals, "All Out omnivamp heal missing"
    attack_damage = sum(
        e.get("damage", 0.0) for e in _main_damage_events(combat, "auto_attacks")
    )
    # Per-packet heals are rounded to 0.1, so the summed heal can differ
    # from the exact 20% by a fraction of a point (autoresearch pass 30
    # changed the R bonus-pen channel, shifting the packet mix).
    assert sum(h["amount"] for h in heals) == pytest.approx(
        0.20 * attack_damage, abs=0.25
    )
    survival = _main_survival(combat)
    assert survival["healing_received"] == pytest.approx(0.20 * attack_damage, abs=0.25)


def test_ksante_without_all_out_authors_no_omnivamp():
    combat = _fight("KSante")
    assert not _omnivamp_heals(combat)
    assert _main_survival(combat)["healing_received"] == 0.0


# ---------------------------------------------------------------------------
# Locke — W Soul Ignition grey-health recast heal
# ---------------------------------------------------------------------------


def test_locke_w_grey_health_recast_heals_the_capped_pool():
    data, stats, _ = _parse("Locke")
    w = data["abilities"]["W"][0]
    cap = extract_named(w, "Damage taken grey health cap", 5, stats, {})
    combat = _fight("Locke", duration=10)
    heals = [h for h in _main_heals(combat, "Soul Ignition (grey health)")]
    assert heals, "Soul Ignition grey-health heal missing"
    survival = _main_survival(combat)
    assert survival["grey_health_stored"] == pytest.approx(cap)
    assert survival["grey_health_consumed"] == pytest.approx(cap)
    # Aatrox's incoming damage over the 6s W window exceeds the rank-5 cap,
    # so the heal pays the sourced cap exactly (120 + 100% AP).
    assert heals[0]["amount"] == pytest.approx(cap)
    assert heals[0]["amount"] == pytest.approx(120.0)


def test_locke_w_rank1_caps_the_pool_lower():
    data, stats, _ = _parse("Locke", ranks={"Q": 5, "W": 1, "E": 5, "R": 3})
    w = data["abilities"]["W"][0]
    cap = extract_named(w, "Damage taken grey health cap", 1, stats, {})
    assert cap == pytest.approx(40.0)
    combat = _fight("Locke", duration=10, ranks={"Q": 5, "W": 1, "E": 5, "R": 3})
    survival = _main_survival(combat)
    assert survival["grey_health_stored"] == pytest.approx(40.0)
    heals = [h for h in _main_heals(combat, "Soul Ignition (grey health)")]
    assert heals and heals[0]["amount"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Malphite — W empowered-attack parts + tripled bonus armor
# ---------------------------------------------------------------------------


def test_malphite_w_prices_empowered_attack_both_parts():
    data, stats, abilities = _parse("Malphite")
    w = data["abilities"]["W"][0]
    armor_grant = extract_named(w, "Increased Bonus Armor", 5, stats, {})
    assert armor_grant == pytest.approx(0.9 * stats["armor"])  # tripled 30%
    buffed = dict(stats)
    buffed["armor"] = stats["armor"] + armor_grant
    on_hit = extract_named(w, "Additional Physical Damage", 5, buffed, {})
    cone = extract_named(w, "Physical Damage", 5, buffed, {})
    part_on_hit, part_cone = abilities["W"]["parts"]
    assert part_on_hit.amount == pytest.approx(on_hit)
    assert part_cone.amount == pytest.approx(cone)
    assert abilities["W"]["total_raw"] == pytest.approx(on_hit + cone)


def test_malphite_e_scales_off_tripled_armor():
    data, stats, abilities = _parse("Malphite")
    w = data["abilities"]["W"][0]
    e = data["abilities"]["E"][0]
    armor_grant = extract_named(w, "Increased Bonus Armor", 5, stats, {})
    buffed = dict(stats)
    buffed["armor"] = stats["armor"] + armor_grant
    expected_e = extract_named(e, "Magic Damage", 5, buffed, {})
    assert abilities["E"]["total_raw"] == pytest.approx(expected_e)
    # The grant is damage-relevant: without it E would price the lower armor.
    assert abilities["E"]["total_raw"] > extract_named(e, "Magic Damage", 5, stats, {})


def test_malphite_api_w_and_e_match_sourced_mitigation():
    combat = _fight("Malphite")
    enemy_stats = _enemy_stats(combat)
    _, stats, abilities = _parse("Malphite")
    w_raw = abilities["W"]["total_raw"]
    e_raw = abilities["E"]["total_raw"]
    w_events = _main_damage_events(combat, "W")
    e_events = _main_damage_events(combat, "E")
    assert w_events and e_events
    # Thunderclap lands its empowered-attack bonus and its cone in one
    # instant but at two magnitudes, so the row's claim is that its events
    # ACCOUNT for the raw total, not that they are equal shares of it.
    assert sum(e["raw_damage"] for e in w_events) == pytest.approx(w_raw, rel=1e-3)
    assert e_events[0]["raw_damage"] == pytest.approx(e_raw / len(e_events), rel=1e-3)
    assert sum(e["damage"] for e in w_events) == pytest.approx(
        w_raw * 100.0 / (100.0 + enemy_stats["armor"]), rel=1e-3
    )
    assert sum(e["damage"] for e in e_events) == pytest.approx(
        e_raw * 100.0 / (100.0 + enemy_stats["magic_resistance"]), rel=1e-3
    )


# ---------------------------------------------------------------------------
# Nasus — P Soul Eater lifesteal
# ---------------------------------------------------------------------------


def _assert_soul_eater_heals(combat, *, level, ratio):
    """Soul Eater heals 12/18/24% of each post-mitigation PHYSICAL hit.

    MERGE: the payments are per damaging physical hit, not per basic
    attack.  Siphoning Strike (Q) is a modified basic attack and pays at
    ITS post-mitigation damage (54.5 at level 18 against 120 armor), while
    a plain auto pays at its own (61.4) -- so the heals come out at two
    magnitudes and one expected value could only ever have matched one of
    them.  That is the wiki's Soul Eater: life steal on physical damage,
    not a per-swing rider.  The level breakpoint (12 / 18 / 24%) is
    unchanged, and it is what the auto-sized heal below still pins.
    """
    from src.calculator.data_fetcher import get_champion

    heals = [h for h in _main_heals(combat, "Soul Eater")]
    assert heals, "Soul Eater heal missing"
    enemy_stats = _enemy_stats(combat)
    nasus_stats = calculate_total_stats(get_champion("Nasus"), level, [])
    per_auto = nasus_stats["attack_damage"] * 100.0 / (100.0 + enemy_stats["armor"])

    physical = [
        event["damage"]
        for event in combat["events"]
        if event.get("attacker") == "main"
        and event.get("damage_type") == "physical"
        and float(event.get("damage", 0.0)) > 0.0
    ]
    assert physical, "no physical hit for Soul Eater to ride"
    for heal in heals:
        assert any(
            heal["amount"] == pytest.approx(ratio * damage, abs=0.06)
            for damage in physical
        ), heal
    # The plain auto's share is the one the level breakpoint names.
    assert any(
        heal["amount"] == pytest.approx(ratio * per_auto, abs=0.06) for heal in heals
    )

    survival = _main_survival(combat)
    if survival["death_time"] is None:
        # The survival walk applies the receipts only while the fighter is
        # alive; a dead-by-first-swing level-6 Nasus still emits the sourced
        # receipts but applies none.
        assert survival["healing_received"] == pytest.approx(
            sum(heal["amount"] for heal in heals), abs=0.25
        )


def test_nasus_soul_eater_heals_twenty_four_percent_at_level_18():
    _assert_soul_eater_heals(_fight("Nasus"), level=18, ratio=0.24)


def test_nasus_soul_eater_heals_twelve_percent_below_level_7():
    # Game-file breakpoints: 12% at levels 1-6, 18% at 7-12, 24% at 13+.
    combat = _fight("Nasus", level=6, ranks={"Q": 2, "W": 1, "E": 2, "R": 1})
    _assert_soul_eater_heals(combat, level=6, ratio=0.12)


# ---------------------------------------------------------------------------
# Rek'Sai — E max-Fury true-damage variant
# ---------------------------------------------------------------------------


def test_reksai_e_prices_physical_bite_by_default():
    data, stats, abilities = _parse("RekSai")
    e = data["abilities"]["E"][0]
    expected = extract_named(e, "Physical Damage", 5, stats, {})
    assert abilities["E"]["total_raw"] == pytest.approx(expected)
    assert abilities["E"]["damage_type"] == "physical"
    combat = _fight("RekSai")
    events = _main_damage_events(combat, "E")
    assert events and events[0]["damage_type"] == "physical"
    assert events[0]["raw_damage"] == pytest.approx(expected / len(events))


def test_reksai_e_at_max_fury_is_true_damage():
    data, stats, abilities = _parse("RekSai", options={"e_fury": 100})
    e = data["abilities"]["E"][0]
    expected = extract_named(e, "True Damage", 5, stats, {})
    assert expected == pytest.approx(204.0)  # 120% of 170 physical
    assert abilities["E"]["total_raw"] == pytest.approx(expected)
    assert abilities["E"]["damage_type"] == "true"
    combat = _fight("RekSai", options={"e_fury": 100})
    events = _main_damage_events(combat, "E")
    assert events and events[0]["damage_type"] == "true"
    # True damage ignores the target's armor entirely at 0 resists.
    assert sum(e["damage"] for e in events) == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# Seraphine — Q missing-health amplifier
# ---------------------------------------------------------------------------


def test_seraphine_q_hp_scaled_part_equals_maximum_enhanced_damage():
    data, stats, abilities = _parse("Seraphine")
    q = data["abilities"]["Q"][0]
    base = extract_named(q, "Magic Damage", 5, stats, {})
    maximum = extract_named(q, "Maximum Enhanced Damage", 5, stats, {})
    assert base == pytest.approx(160.0)
    assert maximum == pytest.approx(280.0)  # 1.75 x base
    flat_part, enhanced_part = abilities["Q"]["parts"]
    assert flat_part.amount == pytest.approx(base)
    assert enhanced_part.hp_scaled_damage(0.0) == pytest.approx(0.0)
    assert enhanced_part.hp_scaled_damage(1.0) == pytest.approx(maximum - base)


def test_seraphine_api_q_always_at_least_the_flat_base():
    # The pair ledger re-prices the hp-scaled part at the defender's live
    # missing-health ratio, so the API total is >= the flat base mitigated
    # against the defender's own magic resistance (the fight's own stats)
    # and <= the Maximum Enhanced Damage row mitigated the same way.
    # The assertion covers High Note's missing-health amplifier. Disable
    # other damaging and control casts so their state does not change the
    # target before Q lands.
    combat = _fight(
        "Seraphine",
        ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
    )
    enemy_stats = _enemy_stats(combat)
    base_mitigated = 160.0 * 100.0 / (100.0 + enemy_stats["magic_resistance"])
    max_mitigated = 280.0 * 100.0 / (100.0 + enemy_stats["magic_resistance"])
    row = _main_breakdown(combat)
    q = next(s for s in row["sources"] if s["name"] == "High Note")
    assert q["total_damage"] >= base_mitigated - 0.05
    assert q["total_damage"] <= max_mitigated + 0.05
    assert q["total_damage"] > base_mitigated + 0.5  # the amp is live


# ---------------------------------------------------------------------------
# Sylas — E2 shield is historical (removed V10.2), no current shield row
# ---------------------------------------------------------------------------


def test_sylas_e_packet_is_complete_without_a_shield():
    data, stats, abilities = _parse("Sylas")
    e = data["abilities"]["E"][1]  # Abduct (the damaging second cast)
    assert "self_shield_events" not in abilities["E"]
    expected = extract_named(e, "Magic Damage", 5, stats, {})
    assert abilities["E"]["total_raw"] == pytest.approx(expected)
    combat = _fight("Sylas")
    assert not _shield_rows(combat, source_startswith="Abscond")
    assert not _shield_rows(combat, source_startswith="Abduct")
    events = _main_damage_events(combat, "E")
    assert events
    assert events[0]["raw_damage"] == pytest.approx(expected / len(events))


# ---------------------------------------------------------------------------
# Vex — P Doom 'n Gloom Gloom detonation (empowered auto)
# ---------------------------------------------------------------------------


def test_vex_p_gloom_detonation_rides_one_basic_attack():
    data, stats, abilities = _parse("Vex")
    passive = data["abilities"]["P"][0]
    expected = extract_named(passive, "Bonus Magic Damage", 18, stats, {})
    assert expected == pytest.approx(150.0)  # L18 flat, 0 AP
    on_hit = abilities["passive"]["on_hit"]
    assert on_hit["damage_per_hit"] == pytest.approx(expected)
    assert on_hit["max_procs"] == 1
    assert on_hit["damage_type"] == "magic"


def test_vex_api_gloom_detonation_deals_sourced_bonus_damage():
    combat = _fight("Vex")
    enemy_stats = _enemy_stats(combat)
    row = _main_breakdown(combat)
    gloom = next(s for s in row["sources"] if s["name"].startswith("Doom 'n Gloom"))
    assert gloom["total_damage"] == pytest.approx(
        _mitigated(150.0, "magic", enemy_stats), rel=1e-3
    )


def test_vex_p_gloom_detonation_count_option_caps_the_rider():
    combat = _fight("Vex", options={"p_gloom_detonations": 3})
    enemy_stats = _enemy_stats(combat)
    row = _main_breakdown(combat)
    gloom = next(s for s in row["sources"] if s["name"].startswith("Doom 'n Gloom"))
    assert gloom["total_damage"] == pytest.approx(
        3 * _mitigated(150.0, "magic", enemy_stats), rel=1e-3
    )
    # Zero detonations emits nothing.
    combat0 = _fight("Vex", options={"p_gloom_detonations": 0})
    row0 = _main_breakdown(combat0)
    assert not [s for s in row0["sources"] if s["name"].startswith("Doom 'n Gloom")]


# ---------------------------------------------------------------------------
# Yasuo — P Intent crit conversion + Q crit-eligible AD portion
# ---------------------------------------------------------------------------


def test_yasuo_q_splits_flat_and_crit_eligible_ad_parts():
    _, stats, abilities = _parse("Yasuo")
    q = abilities["Q"]
    flat_part, ad_part = q["parts"]
    assert flat_part.amount == pytest.approx(120.0)  # rank 5 flat base
    assert flat_part.crit_effectiveness == 0.0
    assert ad_part.amount == pytest.approx(1.05 * stats["attack_damage"])
    assert ad_part.crit_effectiveness == 1.0
    assert q["total_raw"] == pytest.approx(120.0 + 1.05 * stats["attack_damage"])


def test_yasuo_p_crit_conversion_payload_is_sourced():
    _, _, abilities = _parse("Yasuo")
    crit = abilities["passive"]["crit_modifier"]
    assert crit["crit_chance_multiplier"] == 2.0
    assert crit["crit_damage_multiplier_factor"] == 0.9
    assert crit["excess_crit_bonus_ad_per_percent"] == 0.5


def test_yasuo_no_items_auto_damage_has_no_crits():
    combat = _fight("Yasuo")
    events = _main_damage_events(combat, "auto_attacks")
    assert events
    enemy_stats = _enemy_stats(combat)
    _, stats, _ = _parse("Yasuo")
    assert sum(e["damage"] for e in events) == pytest.approx(
        stats["attack_damage"] * 100.0 / (100.0 + enemy_stats["armor"]) * len(events),
        rel=1e-3,
    )


def test_yasuo_crit_conversion_doubles_chance_and_reduces_crit_damage():
    # Infinity Edge (25%) + Phantom Dancer (25%) = 50% crit -> doubled to
    # 100%: every auto crits at 0.9 x (2.0 + 0.30 IE bonus) = 2.07 x AD.
    combat = _fight("Yasuo", items=["Infinity Edge", "Phantom Dancer"])
    enemy_stats = _enemy_stats(combat)
    events = _main_damage_events(combat, "auto_attacks")
    assert events
    from src.calculator.data_fetcher import get_item_by_name

    stats = calculate_total_stats(
        get_champion("Yasuo"),
        18,
        [get_item_by_name("Infinity Edge"), get_item_by_name("Phantom Dancer")],
    )
    assert stats["critical_strike_chance"] == pytest.approx(50.0)
    mitigation = 100.0 / (100.0 + enemy_stats["armor"])
    per_hit = sum(e["damage"] for e in events) / len(events)
    assert per_hit == pytest.approx(
        stats["attack_damage"] * 2.07 * mitigation, rel=0.01
    )
