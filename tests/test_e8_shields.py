"""E8c — champion shield events (14 champions).

Every shield is authored through the existing ledger interface:
- module-authored ``self_shield_events`` payloads ride a damaging
  ability's first event (Ambessa W, Blitzcrank P via Q, Camille P via
  W, Malphite P via Q, Senna R self-half, Volibear E, Vex W) and the
  shared ledger grants a timed self-shield at that timestamp;
- JSON-scanner packets from ``derive_ally_effects`` emit the cached
  Shield Strength rows at the cast for the remaining actives (Annie E,
  Azir E, Olaf W) and the ally-targeted halves (Senna R, Thresh W);
- Braum E, Leona W, and Nilah P are documented mitigation/conversion
  state with sourced constants (the ledger's shield events cannot
  price projectile blocks, per-instance pre-mitigation reduction, or
  live excess-heal conversion), and the tests assert no flat shield is
  invented for them.
"""

import json

import pytest

from src.app import app
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.slotlib import extract_named
from src.calculator.data_fetcher import get_champion

DEFAULT_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(champion, *, level=18, stats=None, options=None, ranks=None):
    data = get_champion(champion)
    base_stats = {
        "ability_power": 100.0,
        "health": 2000.0,
        "max_mana": 1000.0,
        "bonus_attack_damage": 50.0,
        "attack_damage": 150.0,
    }
    if stats:
        base_stats.update(stats)
    return data, parse_champion_abilities(
        data,
        level,
        base_stats["ability_power"],
        ability_ranks=ranks or dict(DEFAULT_RANKS),
        champion_stats=base_stats,
        champion_options=options,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
    )


def _run_api_fight(champion, *, enemy="Aatrox", duration=6, allies=None, ranks=None):
    # TESTING is scoped to this request and restored afterwards: the flag
    # is session-global, and a module-level assignment would leak into
    # every later test file (the rate-limiter short-circuits on TESTING).
    previous_testing = app.config.get("TESTING")
    app.config["TESTING"] = True
    try:
        return _post_fight(
            champion,
            enemy=enemy,
            duration=duration,
            allies=allies,
            ranks=ranks,
        )
    finally:
        if previous_testing is None:
            app.config.pop("TESTING", None)
        else:
            app.config["TESTING"] = previous_testing


def _post_fight(champion, *, enemy="Aatrox", duration=6, allies=None, ranks=None):
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "ability_ranks": dict(ranks or DEFAULT_RANKS),
        "enemies": [{"champion": enemy, "level": 18, "items": []}],
    }
    if allies:
        payload["allies"] = allies
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _shield_rows(combat, *, source_startswith):
    return [
        event
        for event in combat.get("support_events", [])
        if event.get("kind") == "shield"
        and str(event.get("source", "")).startswith(source_startswith)
    ]


def _main_survival(combat):
    return next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )["survival"]


# ---------------------------------------------------------------------------
# Annie E — Molten Shield (scanner-emitted: flat + 40% AP at the cast)
# ---------------------------------------------------------------------------


def test_annie_molten_shield_amount_is_sourced():
    data, _ = _parse("Annie")
    ability = data["abilities"]["E"][0]
    assert extract_named(
        ability, "Shield Strength", 5, {"ability_power": 100.0}
    ) == pytest.approx(
        240.0
    )  # 200 + 40% AP


def test_annie_api_molten_shield_row_absorbs_sourced_amount():
    combat = _run_api_fight("Annie")
    rows = _shield_rows(combat, source_startswith="Molten Shield")
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(200.0)  # rank 5 flat, 0 AP
    assert rows[0]["duration"] == pytest.approx(3.0)
    assert rows[0]["expires_at"] == pytest.approx(3.0)
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(200.0)
    assert survival["shield_absorbed"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Azir E — Shifting Sands (scanner-emitted: flat + 60% AP at the cast)
# ---------------------------------------------------------------------------


def test_azir_shifting_sands_shield_amount_is_sourced():
    data, _ = _parse("Azir")
    ability = data["abilities"]["E"][0]
    assert extract_named(
        ability, "Shield Strength", 5, {"ability_power": 100.0}
    ) == pytest.approx(
        290.0
    )  # 230 + 60% AP


def test_azir_api_shifting_sands_row_absorbs_sourced_amount():
    combat = _run_api_fight("Azir")
    rows = _shield_rows(combat, source_startswith="Shifting Sands")
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(230.0)  # rank 5 flat, 0 AP
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(230.0)
    assert survival["shield_absorbed"] == pytest.approx(230.0)


# ---------------------------------------------------------------------------
# Ambessa W — Repudiation (module-authored: level base + 150% bonus AD)
# ---------------------------------------------------------------------------


def test_ambessa_repudiation_shield_payload_is_level_indexed():
    _, abilities = _parse("Ambessa")
    (shield,) = abilities["W"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(395.0)  # 320 (L18) + 150% x 50 bAD
    assert shield["duration"] == pytest.approx(1.5)
    assert shield["source"] == "Repudiation"
    _, low = _parse(
        "Ambessa",
        level=1,
        stats={"bonus_attack_damage": 0.0},
        ranks={"Q": 1, "W": 1, "E": 1, "R": 1},
    )
    (low_shield,) = low["W"]["self_shield_events"]
    assert low_shield["amount"] == pytest.approx(50.0)  # 50 at level 1


def test_ambessa_api_repudiation_row_absorbs_sourced_amount():
    combat = _run_api_fight("Ambessa")
    rows = _shield_rows(combat, source_startswith="Repudiation")
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(320.0)  # L18 base, 0 bonus AD
    assert rows[0]["duration"] == pytest.approx(1.5)
    # The JSON scanner defers this slot: no rank-indexed duplicate row.
    assert not _shield_rows(combat, source_startswith="Repudiation · Shield")
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(320.0)
    assert survival["shield_absorbed"] == pytest.approx(320.0)


# ---------------------------------------------------------------------------
# Blitzcrank P — Mana Barrier (module-authored pre-fight shield on Q)
# ---------------------------------------------------------------------------


def test_blitzcrank_mana_barrier_payload_is_sourced():
    _, abilities = _parse("Blitzcrank", stats={"max_mana": 1000.0})
    (shield,) = abilities["Q"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(350.0)  # 35% of 1000 max mana
    assert shield["duration"] == pytest.approx(10.0)
    assert shield["source"] == "Mana Barrier"


def test_blitzcrank_api_mana_barrier_absorbs_sourced_amount():
    combat = _run_api_fight("Blitzcrank")
    rows = _shield_rows(combat, source_startswith="Mana Barrier")
    assert len(rows) == 1
    survival = _main_survival(combat)
    # The receipt rounds support_shield_received/shield_absorbed to 1 decimal.
    assert rows[0]["amount"] == pytest.approx(
        survival["support_shield_received"], abs=0.06
    )
    assert survival["shield_absorbed"] == pytest.approx(rows[0]["amount"], abs=0.06)


# ---------------------------------------------------------------------------
# Braum E — Unbreakable (documented CC/mitigation state, no flat shield)
# ---------------------------------------------------------------------------


def test_braum_unbreakable_is_documented_mitigation_not_a_flat_shield():
    _, abilities = _parse(
        "Braum",
        options={
            "e_active": True,
            "e_blocked_skillshots": ["Ezreal:Q"],
        },
    )
    defense = abilities["E"]["defensive_interaction"]
    assert defense["kind"] == "braum_unbreakable"
    assert defense["damage_reduction"] == pytest.approx(0.55)
    assert defense["blocked_sources"] == ["Ezreal:Q"]
    combat = _run_api_fight("Braum")
    assert not [
        e for e in combat.get("support_events", []) if e.get("kind") == "shield"
    ]
    assumptions = " ".join(
        assumption
        for assumption in __import__(
            "src.calculator.champions.braum", fromlist=["ASSUMPTIONS"]
        ).ASSUMPTIONS
    )
    assert "Unbreakable" in assumptions and "Damage reduction" in assumptions


# ---------------------------------------------------------------------------
# Camille P — Adaptive Defenses (module-authored pre-fight shield on W)
# ---------------------------------------------------------------------------


def test_camille_adaptive_defenses_payload_is_sourced():
    _, abilities = _parse("Camille")
    (shield,) = abilities["W"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(400.0)  # 20% of 2000 max HP
    assert shield["duration"] == pytest.approx(2.0)
    assert shield["source"] == "Adaptive Defenses"


def test_camille_api_adaptive_defenses_absorbs_known_incoming_hit():
    combat = _run_api_fight("Camille", ranks={"Q": 5, "W": 5, "E": 0, "R": 3})
    rows = _shield_rows(combat, source_startswith="Adaptive Defenses")
    assert len(rows) == 1
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(rows[0]["amount"])
    # F2 order note: Aatrox now opens with its optimal zero-damage
    # World Ender, so the first hit (Q) lands at t=0.25 — inside the 2s
    # Adaptive Defenses window.  The shield absorbs the entire sourced
    # amount and can never exceed it.
    assert 0 < survival["shield_absorbed"] <= rows[0]["amount"]
    assert survival["shield_absorbed"] == pytest.approx(rows[0]["amount"])


# ---------------------------------------------------------------------------
# Malphite P — Granite Shield (module-authored pre-fight shield on Q)
# ---------------------------------------------------------------------------


def test_malphite_granite_shield_payload_is_sourced():
    _, abilities = _parse("Malphite", options={"fight_duration_seconds": 5.0})
    (shield,) = abilities["Q"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(200.0)  # 10% of 2000 max HP
    assert shield["duration"] == pytest.approx(5.0)  # until broken = window
    assert shield["source"] == "Granite Shield"


def test_malphite_api_granite_shield_absorbs_sourced_amount():
    combat = _run_api_fight("Malphite", duration=6)
    rows = _shield_rows(combat, source_startswith="Granite Shield")
    assert len(rows) == 1
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(rows[0]["amount"])
    assert survival["shield_absorbed"] == pytest.approx(rows[0]["amount"])


# ---------------------------------------------------------------------------
# Senna R — Dawning Shadow (self-half module-authored; ally half scanner)
# ---------------------------------------------------------------------------


def test_senna_dawning_shadow_self_shield_includes_mist_term():
    _, abilities = _parse("Senna", options={"senna_mist_stacks": 40})
    (shield,) = abilities["R"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(310.0)  # 200 + 50% AP + 150% x 40
    assert shield["duration"] == pytest.approx(3.0)
    assert shield["source"] == "Dawning Shadow"


def test_senna_api_dawning_shadow_shields_senna_and_selected_ally():
    combat = _run_api_fight(
        "Senna",
        allies=[
            {
                "champion": "Jinx",
                "level": 18,
                "items": [],
                "role": "bottom",
                "ally_effects_enabled": True,
            }
        ],
    )
    self_rows = _shield_rows(combat, source_startswith="Dawning Shadow")
    assert len(self_rows) == 2  # module self-half + scanner ally-half
    self_row = next(row for row in self_rows if row["target"] == "main")
    ally_row = next(row for row in self_rows if row["target"] == "ally:Jinx")
    assert self_row["amount"] == pytest.approx(260.0)  # 200 + 150% x 40 Mist
    assert self_row["duration"] == pytest.approx(3.0)
    # Scanner ally packet prices flat + AP only (no Mist term).
    assert ally_row["amount"] == pytest.approx(200.0)
    survival = _main_survival(combat)
    assert survival["shield_absorbed"] == pytest.approx(260.0)


# ---------------------------------------------------------------------------
# Thresh W — Dark Passage (ally shield via the existing support interface)
# ---------------------------------------------------------------------------


def test_thresh_dark_passage_ally_shield_flows_to_selected_teammate():
    combat = _run_api_fight(
        "Thresh",
        allies=[
            {
                "champion": "Jinx",
                "level": 18,
                "items": [],
                "role": "bottom",
                "ally_effects_enabled": True,
            }
        ],
    )
    rows = _shield_rows(combat, source_startswith="Dark Passage")
    assert len(rows) == 1
    assert rows[0]["target"] == "ally:Jinx"
    assert rows[0]["amount"] == pytest.approx(130.0)  # rank 5 flat
    assert rows[0]["duration"] == pytest.approx(4.0)
    assert rows[0]["duration_atom"]["atom_id"] == "timing.shield_duration"
    jinx = next(
        row for row in combat["participants"] if row["participant_id"] == "ally:Jinx"
    )["survival"]
    assert jinx["support_shield_received"] == pytest.approx(130.0)


def test_thresh_dark_passage_has_no_self_packet_in_a_1v1():
    # The scanner's description markers treat Dark Passage as an ally-only
    # packet; with no selected teammate the ledger drops it (documented
    # boundary), so a 1v1 emits no fabricated Thresh self-shield.
    combat = _run_api_fight("Thresh")
    assert not [
        e for e in combat.get("support_events", []) if e.get("kind") == "shield"
    ]


# ---------------------------------------------------------------------------
# Volibear E — Sky Splitter (module-authored: 14% max HP + 75% AP)
# ---------------------------------------------------------------------------


def test_volibear_sky_splitter_shield_payload_is_sourced():
    _, abilities = _parse("Volibear")
    (shield,) = abilities["E"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(355.0)  # 14% x 2000 + 75% x 100 AP
    assert shield["duration"] == pytest.approx(3.0)
    assert shield["source"] == "Sky Splitter"


def test_volibear_api_sky_splitter_absorbs_sourced_amount():
    combat = _run_api_fight("Volibear")
    rows = _shield_rows(combat, source_startswith="Sky Splitter")
    assert len(rows) == 1
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(
        rows[0]["amount"], abs=0.06
    )
    assert survival["shield_absorbed"] == pytest.approx(rows[0]["amount"], abs=0.06)


# ---------------------------------------------------------------------------
# Vex W — Personal Space (module-authored self shield; scanner defers)
# ---------------------------------------------------------------------------


def test_vex_personal_space_shield_payload_is_sourced():
    _, abilities = _parse("Vex")
    (shield,) = abilities["W"]["self_shield_events"]
    assert shield["amount"] == pytest.approx(225.0)  # 150 + 75% x 100 AP
    assert shield["duration"] == pytest.approx(2.5)
    assert shield["source"] == "Personal Space"


def test_vex_api_personal_space_absorbs_sourced_amount():
    combat = _run_api_fight("Vex")
    rows = _shield_rows(combat, source_startswith="Personal Space")
    assert len(rows) == 1
    assert rows[0]["duration"] == pytest.approx(2.5)
    # Scanner deferral: no mis-targeted "Personal Space · Shield Strength".
    assert not _shield_rows(combat, source_startswith="Personal Space ·")
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(150.0)
    assert survival["shield_absorbed"] == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# Leona W — Eclipse (documented mitigation state, no flat shield)
# ---------------------------------------------------------------------------


def test_leona_eclipse_is_documented_mitigation_not_a_flat_shield():
    from src.calculator.champions.leona import (
        _ECLIPSE_BONUS_RESIST_RANKED,
        _ECLIPSE_FLAT_REDUCTION_RANKED,
        _ECLIPSE_REDUCTION_CAP,
    )

    assert _ECLIPSE_FLAT_REDUCTION_RANKED == (8.0, 12.0, 16.0, 20.0, 24.0)
    assert _ECLIPSE_BONUS_RESIST_RANKED == (20.0, 27.5, 35.0, 42.5, 50.0)
    assert _ECLIPSE_REDUCTION_CAP == pytest.approx(0.50)
    combat = _run_api_fight("Leona")
    assert not [
        e for e in combat.get("support_events", []) if e.get("kind") == "shield"
    ]


# ---------------------------------------------------------------------------
# Olaf W — Tough It Out (scanner-emitted flat; missing-HP documented)
# ---------------------------------------------------------------------------


def test_olaf_tough_it_out_shield_amount_is_sourced():
    data, _ = _parse("Olaf")
    ability = data["abilities"]["W"][0]
    # Full-health floor: the scanner evaluates the missing-health term at 0.
    assert extract_named(ability, "Shield Strength", 5, {}, {}) == pytest.approx(130.0)
    from src.calculator.champions.olaf import (
        TOUGH_IT_OUT_MISSING_HEALTH_RATIO,
        TOUGH_IT_OUT_SHIELD_DURATION_SECONDS,
    )

    assert TOUGH_IT_OUT_MISSING_HEALTH_RATIO == pytest.approx(0.175)
    assert TOUGH_IT_OUT_SHIELD_DURATION_SECONDS == pytest.approx(2.5)


def test_olaf_api_tough_it_out_absorbs_sourced_amount():
    combat = _run_api_fight("Olaf")
    rows = _shield_rows(combat, source_startswith="Tough It Out")
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(130.0)
    survival = _main_survival(combat)
    assert survival["support_shield_received"] == pytest.approx(130.0)
    assert survival["shield_absorbed"] == pytest.approx(130.0)


# ---------------------------------------------------------------------------
# Nilah P — Joy Unending (documented heal-to-shield conversion)
# ---------------------------------------------------------------------------


def test_nilah_joy_unending_conversion_is_documented_with_sourced_ratios():
    from src.calculator.champions.nilah import (
        _NILAH_EXCESS_SHIELD_DURATION_SECONDS,
        _NILAH_Q_HEAL_TO_SHIELD_MAX_RATIO,
        _NILAH_R_HEAL_TO_SHIELD_MIN_RATIO,
    )

    assert _NILAH_Q_HEAL_TO_SHIELD_MAX_RATIO == pytest.approx(0.20)
    assert _NILAH_R_HEAL_TO_SHIELD_MIN_RATIO == pytest.approx(0.20)
    assert _NILAH_EXCESS_SHIELD_DURATION_SECONDS == pytest.approx(6.0)
    combat = _run_api_fight("Nilah")
    # Excess-heal conversion is live state; no flat shield is invented.
    assert not [
        e for e in combat.get("support_events", []) if e.get("kind") == "shield"
    ]
