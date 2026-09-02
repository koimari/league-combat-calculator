"""P1-2: zero-review closures — Aphelios, Karthus, Lulu, MasterYi,
Nautilus, Rell, Shaco, Udyr, Viktor, Yunara.

Every champion drives /api/calculate fights at level 18 (basic abilities
rank 5, ultimates rank 3 — level-derived for Udyr, which rejects manual
ranks), no items, and the E3 simple-target convention (target_health
2000, target armor/MR 0 so post-mitigation damage equals the raw wiki
values).  Expected numbers are recomputed from data/champions.json
leveling rows plus the fight's own stats (``calculate_total_stats`` at
level 18 with no items), so every asserted value traces to the cache or
an explicitly cited module constant.

Heal/shield receipts (Aphelios Severum overheal shield, Master Yi
Meditate, Rell/Nautilus/Viktor shields) are asserted against
enemies=[Ahri] fights, which produce the coupled participant ledger.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import (
    _CHAMPION_MODULES,
    get_champion_module_contract,
    module_basename,
    parse_champion_abilities,
)
from src.calculator.champions.slotlib import extract_named
from src.calculator.healing import derive_self_healing
from src.calculator.stats import calculate_total_stats

_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_ENEMY = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    # Keep support amount assertions independent of incoming Ahri Charm
    # downtime. Control timing has dedicated interaction tests.
    "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
}
_TARGET_2000 = {"target_max_health": 2000.0, "target_current_health": 2000.0}
_ROUNDING = 0.6


def _stats(champion: str) -> dict:
    """The app's level-18 no-item stats for one champion."""
    return calculate_total_stats(_DATA[champion], 18, [])


def _parse(
    champion: str,
    *,
    options: dict | None = None,
    target: dict | None = _TARGET_2000,
    ranks: dict | None = _FULL_RANKS,
) -> dict:
    """parse_champion_abilities at level 18 with the fight's own stats."""
    stats = _stats(champion)
    return parse_champion_abilities(
        _DATA[champion],
        18,
        stats["ability_power"],
        ability_ranks=ranks,
        champion_options=options or {},
        champion_stats=stats,
        target_stats=target,
    )


def _fight(
    champion: str,
    *,
    options: dict | None = None,
    include_autos: bool = False,
    mode: str = "one_rotation",
    duration: float = 5.0,
    ranks: dict | None = _FULL_RANKS,
) -> dict:
    """One /api/calculate fight, simple 2000-HP target with 0 resists."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "fight_mode": mode,
        "fight_duration": duration,
        "include_auto_attacks": include_autos,
        "champion_options": options or {},
        "target_health": 2000,
        "target_armor": 0,
        "target_mr": 0,
    }
    if ranks is not None:
        payload["ability_ranks"] = ranks
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _fight_enemy(
    champion: str,
    *,
    options: dict | None = None,
    enemy_ranks: dict | None = _FULL_RANKS,
    include_autos: bool = False,
    mode: str = "one_rotation",
    duration: float = 5.0,
) -> dict:
    """One /api/calculate fight into an Ahri enemy (the coupled ledger)."""
    enemy = dict(_ENEMY)
    enemy["ability_ranks"] = enemy_ranks
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "top",
        "fight_mode": mode,
        "fight_duration": duration,
        "include_auto_attacks": include_autos,
        "champion_options": options or {},
        "enemies": [enemy],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _main_support(data: dict, source_substring: str) -> list[dict]:
    return [
        s
        for s in data["combat"].get("support_events", [])
        if s.get("attacker") == "main"
        and source_substring.lower() in str(s.get("source", "")).lower()
    ]


# ---------------------------------------------------------------------------
# Aphelios — Severum overheal -> shield
# ---------------------------------------------------------------------------


class TestAphelios:
    """The E1 Severum heal already fires; P1-2 adds the overheal shield."""

    def test_severum_q_and_r_damage(self) -> None:
        stats = _stats("Aphelios")
        data = _fight("Aphelios", options={"aphelios_main_weapon": "severum"})
        bonus_as = float(stats.get("bonus_attack_speed", 0.0))
        count = max(1, int(6 + 2 * bonus_as / 100.0))
        per_hit = 0.41 * float(stats["attack_damage"])  # level-18 ratio
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            per_hit * count, abs=_ROUNDING
        )
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(225.0)

    def test_r_detail_stamps_overheal_shield_marker(self) -> None:
        abilities = _parse("Aphelios", options={"aphelios_main_weapon": "severum"})
        assert "overheal shield on" in abilities["R"]["detail"]

    def test_severum_overheal_converts_to_timed_shield(self) -> None:
        """At full health the heal is all excess: the sourced cap (10 : 160
        by level + 6% maximum health) converts it into a timed shield."""
        data = _fight_enemy(
            "Aphelios",
            options={"aphelios_main_weapon": "severum"},
            enemy_ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
        )
        main = next(
            p for p in data["combat"]["participants"] if p["participant_id"] == "main"
        )
        assert main["survival"]["support_shield_received"] > 0.0
        heals = [
            h
            for h in data["combat"]["healing_events"]
            if h.get("attacker") == "main" and h.get("source") == "Severum"
        ]
        assert heals
        # Every heal is all excess (applied_amount 0) and the walk converts
        # each into the timed shield instead of wasting it (overheal 0), so
        # the shield receipt equals what the heals were worth.  Onslaught's
        # six attacks are six of those heals, one per attack.
        assert all(float(heal["applied_amount"]) == 0.0 for heal in heals)
        assert all(float(heal["overheal"]) == 0.0 for heal in heals)
        # The response rounds each heal to one decimal, so the tolerance
        # grows with the number of rows summed.
        assert float(main["survival"]["support_shield_received"]) == pytest.approx(
            sum(float(heal["amount"]) for heal in heals),
            abs=0.15 + 0.05 * len(heals),
        )
        # The cap: 160 (level 18 flat) + 6% maximum health.
        cap = 160.0 + 0.06 * float(main["survival"]["max_health"])
        assert float(main["survival"]["support_shield_received"]) <= cap + 0.2

    def test_overheal_shield_option_off(self) -> None:
        data = _fight_enemy(
            "Aphelios",
            options={
                "aphelios_main_weapon": "severum",
                "aphelios_overheal_shield": False,
            },
            enemy_ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
        )
        main = next(
            p for p in data["combat"]["participants"] if p["participant_id"] == "main"
        )
        assert main["survival"]["support_shield_received"] == 0.0


# ---------------------------------------------------------------------------
# Karthus — Death Defied documented receipt
# ---------------------------------------------------------------------------


class TestKarthus:
    """Death Defied is a death-only trigger: P becomes a zero-damage
    receipt with the sourced boundary, and the alive-state package is
    unchanged (total_damage stays Q + E + R)."""

    def test_passive_receipt_is_zero_damage_and_documented(self) -> None:
        abilities = _parse("Karthus")
        passive = abilities["passive"]
        assert passive["name"] == "Death Defied"
        assert passive["total_raw"] == 0.0
        assert passive["parts"] == ()
        assert "death-only trigger" in passive["detail"]

    def test_alive_state_totals_unchanged(self) -> None:
        data = _fight("Karthus")
        # W debuff + Q 232 + E 5x27.5 + R 500 at 0 resists.
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(232.0)
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(137.5)
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Lulu — P Pix bolt barrage on-hit
# ---------------------------------------------------------------------------


class TestLulu:
    """P: 3 bolts per basic attack, each the per-level row + 5% AP."""

    def test_pix_bolts_on_hit(self) -> None:
        data = _fight("Lulu", include_autos=True, mode="time_based", duration=5.0)
        row = data["breakdown"]["on_hit_ability_passive"]
        # 3 bolts x 39 (level-18 per-bolt flat) + 0 AP.
        assert row["damage_per_hit"] == pytest.approx(3 * 39.0, abs=0.1)
        assert row["total_damage"] == pytest.approx(
            row["damage_per_hit"] * row["count"], abs=_ROUNDING
        )

    def test_pix_bolts_option(self) -> None:
        data = _fight(
            "Lulu",
            options={"lulu_pix_bolts": 1},
            include_autos=True,
            mode="time_based",
            duration=5.0,
        )
        row = data["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(39.0, abs=0.1)


# ---------------------------------------------------------------------------
# Master Yi — W Meditate heal stream
# ---------------------------------------------------------------------------


class TestMasterYi:
    """W: 8 ticks at 0.5s over the 4s channel, missing-health scaled."""

    def test_meditate_heal_rule_emits_eight_ticks(self) -> None:
        stats = _stats("MasterYi")
        heals = derive_self_healing(
            _DATA["MasterYi"],
            stats,
            {"W": {"rank": 5}},
            [],
            cast_timeline=[{"time": 0.0, "slot": "W"}],
            fight_duration_seconds=4.0,
        )
        meditate = [h for h in heals if h.get("source") == "Meditate"]
        assert len(meditate) == 8
        assert [round(float(h["time"]), 2) for h in meditate] == [
            0.5,
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            4.0,
        ]
        # At full health the tick pays the Minimum Heal Per Tick row
        # (55 + 12.5% AP at rank 5).
        formula = meditate[0]["amount_formula"]
        assert float(formula(stats["health"], stats["health"])) == pytest.approx(55.0)

    def test_meditate_heals_in_fight(self) -> None:
        data = _fight_enemy(
            "MasterYi",
            mode="time_based",
            duration=4.0,
            include_autos=False,
            enemy_ranks={"Q": 5, "W": 5, "E": 0, "R": 3},
        )
        heals = [
            h
            for h in data["combat"]["healing_events"]
            if h.get("attacker") == "main" and h.get("source") == "Meditate"
        ]
        assert len(heals) == 8
        assert all(float(h["raw_amount"]) >= 55.0 - 0.2 for h in heals)

    def test_w_slot_is_casted(self) -> None:
        data = _fight("MasterYi")
        assert data["breakdown"]["W"]["total_damage"] == 0.0


# ---------------------------------------------------------------------------
# Nautilus — W two-instance Total Magic Damage + R primary-target damage
# ---------------------------------------------------------------------------


class TestNautilus:
    """W prices Total Magic Damage (70 at rank 5) across its two sourced
    instances; R prices the primary-target Increased Damage (400 at rank
    3); the W shield is scanner-emitted."""

    def test_w_prices_total_across_two_instances(self) -> None:
        data = _fight("Nautilus")
        assert data["breakdown"]["W"]["total_damage"] == pytest.approx(70.0)
        events = _fight_enemy("Nautilus")
        w_events = [
            e
            for e in events["combat"]["events"]
            if e.get("attacker") == "main" and e.get("source") == "W"
        ]
        assert len(w_events) == 2
        assert sum(float(e["raw_damage"]) for e in w_events) == pytest.approx(70.0)

    def test_r_prices_primary_target_increased_damage(self) -> None:
        data = _fight("Nautilus")
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(400.0)

    def test_w_shield_emitted(self) -> None:
        data = _fight_enemy("Nautilus")
        shields = _main_support(data, "Titan's Wrath")
        assert shields
        stats = _stats("Nautilus")
        expected = extract_named(
            _DATA["Nautilus"]["abilities"]["W"][0],
            "Shield Strength",
            5,
            stats,
            _TARGET_2000,
        )
        assert float(shields[0]["amount"]) == pytest.approx(expected, abs=0.2)


# ---------------------------------------------------------------------------
# Rell — P on-hit, W shield, E modeled
# ---------------------------------------------------------------------------


class TestRell:
    """P deals 5% armor + 5% MR magic on-hit; W's Crash Down shield is a
    self shield; E Full Tilt is modeled."""

    def test_p_break_the_mold_on_hit(self) -> None:
        stats = _stats("Rell")
        expected_per_hit = 0.05 * (stats["armor"] + stats["magic_resistance"])
        data = _fight("Rell", include_autos=True, mode="time_based", duration=5.0)
        row = data["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(expected_per_hit, abs=0.1)
        assert row["total_damage"] == pytest.approx(
            row["damage_per_hit"] * row["count"], abs=_ROUNDING
        )

    def test_w_shield_emitted_as_self_shield(self) -> None:
        data = _fight_enemy("Rell")
        shields = _main_support(data, "Ferromancy: Crash Down")
        assert shields
        assert shields[0]["target_scope"] == "self"
        stats = _stats("Rell")
        expected = extract_named(
            _DATA["Rell"]["abilities"]["W"][0],
            "Shield Strength",
            5,
            stats,
            _TARGET_2000,
        )
        assert float(shields[0]["amount"]) == pytest.approx(expected, abs=0.2)

    def test_e_full_tilt_is_modeled(self) -> None:
        data = _fight("Rell")
        # 7% of the 2000-HP target + 3% per 100 AP (0 AP) at rank 5.
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(140.0)


# ---------------------------------------------------------------------------
# Shaco — E execute row + R clone option
# ---------------------------------------------------------------------------


class TestShaco:
    """E prices the <30%-HP Increased Damage row when e_execute is on; R's
    controllable clone is r_clone_attacks x 75% AD physical."""

    def test_e_default_base_row(self) -> None:
        data = _fight("Shaco")
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(170.0)

    def test_e_execute_row_option(self) -> None:
        data = _fight("Shaco", options={"e_execute": True})
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(255.0)

    def test_r_clone_attacks_option(self) -> None:
        stats = _stats("Shaco")
        data = _fight("Shaco", options={"r_clone_attacks": 3})
        clone = 3 * 0.75 * float(stats["attack_damage"])
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(
            300.0 + clone, abs=_ROUNDING
        )


# ---------------------------------------------------------------------------
# Udyr — Q Wilding Claw empowered attacks (+ Awaken)
# ---------------------------------------------------------------------------


class TestUdyr:
    """Q's stance empowers 2 basic attacks with the sourced on-hit payload
    (7% max health + 3.5% per 100 bonus AD, plus the 4s on-hit flat);
    q_awaken adds the per-level Max Health Damage row and the lightning
    chain."""

    def test_q_empowered_attacks_on_hit(self) -> None:
        data = _fight(
            "Udyr", include_autos=True, mode="time_based", duration=5.0, ranks=None
        )
        row = data["breakdown"]["on_hit_ability_Q"]
        # rank 5: 7% of 2000 + 3.5% per 100 bonus AD (0) + flat 30.
        expected_per_hit = 0.07 * 2000.0 + 30.0
        assert row["damage_per_hit"] == pytest.approx(expected_per_hit, abs=0.1)
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(expected_per_hit * 2, abs=0.6)

    def test_q_awaken_adds_max_health_and_lightning(self) -> None:
        data = _fight(
            "Udyr",
            options={"q_awaken": True},
            include_autos=True,
            mode="time_based",
            duration=5.0,
            ranks=None,
        )
        on_hit = data["breakdown"]["on_hit_ability_Q"]
        # level 18: 4.0% of 2000 extra physical per empowered attack.
        assert on_hit["total_damage"] == pytest.approx(
            (0.07 * 2000.0 + 30.0 + 0.04 * 2000.0) * 2, abs=0.6
        )
        # lightning: 6 strikes x 2 attacks x 3.0% of 2000 magic.
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            6 * 2 * (0.03 * 2000.0), abs=0.6
        )


# ---------------------------------------------------------------------------
# Viktor — Q shield + Discharge empowered auto
# ---------------------------------------------------------------------------


class TestViktor:
    """Q grants the per-level shield (140 at level 18) for 2.5s and its
    Discharge empowers the next basic attack (Modified Magic Damage)."""

    def test_q_shield_emitted(self) -> None:
        data = _fight_enemy("Viktor")
        shields = _main_support(data, "Siphon Power")
        assert shields
        assert float(shields[0]["amount"]) == pytest.approx(140.0, abs=0.2)
        assert float(shields[0]["duration"]) == pytest.approx(2.5)

    def test_q_discharge_on_hit(self) -> None:
        stats = _stats("Viktor")
        expected = 120.0 + 1.0 * float(stats["attack_damage"])
        data = _fight("Viktor", include_autos=True, mode="time_based", duration=5.0)
        row = data["breakdown"]["on_hit_ability_Q"]
        assert row["count"] == 1
        assert row["damage_per_hit"] == pytest.approx(expected, abs=0.1)

    def test_q_discharge_option_off(self) -> None:
        data = _fight(
            "Viktor",
            options={"q_discharge": False},
            include_autos=True,
            mode="time_based",
            duration=5.0,
        )
        assert "on_hit_ability_Q" not in data["breakdown"]


# ---------------------------------------------------------------------------
# Yunara — W linger beads + R as buff
# ---------------------------------------------------------------------------


class TestYunara:
    """W prices the initial impact plus 4 linger ticks (15% of impact per
    0.25s; per-tick row x 4 == Total Expanded Damage); R is a zero-damage
    buff with the r_transcendent option switching W to Arc of Ruin."""

    def test_w_prices_initial_plus_linger_ticks(self) -> None:
        data = _fight("Yunara")
        assert data["breakdown"]["W"]["total_damage"] == pytest.approx(
            215.0 + 4 * 32.25, abs=_ROUNDING
        )
        events = _fight_enemy("Yunara")
        w_events = [
            e
            for e in events["combat"]["events"]
            if e.get("attacker") == "main" and e.get("source") == "W"
        ]
        assert len(w_events) == 5  # impact + 4 linger ticks

    def test_r_is_zero_damage_buff(self) -> None:
        data = _fight("Yunara")
        assert data["breakdown"]["R"]["total_damage"] == 0.0

    def test_r_transcendent_prices_arc_of_ruin(self) -> None:
        data = _fight("Yunara", options={"r_transcendent": True})
        assert data["breakdown"]["W"]["total_damage"] == pytest.approx(480.0)


# ---------------------------------------------------------------------------
# Module coverage flags are consistent with the closed slots
# ---------------------------------------------------------------------------


class TestCoverageFlags:
    def test_audit_flagged_slots_are_modeled(self) -> None:

        # Every audit-flagged slot (the P1-2 closure list) must be marked
        # modeled in its module's MODULE_COVERAGE.
        expectations = {
            "rell": {"P": "modeled", "E": "modeled"},
            "udyr": {"Q": "modeled", "W": "modeled", "R": "modeled"},
            "lulu": {"P": "modeled"},
            "master_yi": {
                "P": "modeled",
                "W": "modeled",
                "Q": "modeled",
                "E": "modeled",
            },
            "nautilus": {"P": "modeled", "W": "modeled", "R": "modeled"},
            "viktor": {"Q": "modeled", "E": "modeled", "R": "modeled"},
            "yunara": {
                "P": "modeled",
                "Q": "modeled",
                "W": "modeled",
                "E": "modeled",
                "R": "modeled",
            },
            "shaco": {"Q": "modeled", "W": "modeled", "E": "modeled", "R": "modeled"},
        }
        for module_name, flagged in expectations.items():
            name = next(
                display
                for display, candidate in _CHAMPION_MODULES.items()
                if module_basename(candidate) == module_name
            )
            coverage = get_champion_module_contract(name).coverage
            for slot, status in flagged.items():
                assert coverage[slot] == status, f"{module_name} {slot}"
