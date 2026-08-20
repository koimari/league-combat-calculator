"""E9-2 gap-fix tests (Ahri, Illaoi, Kled, LeeSin, Naafiri, Pantheon,
Renata, Sion, Smolder, Urgot).

Each test drives /api/calculate fights (level 18, rank 5 / R rank 3, no
items, 0 resists unless noted) and asserts the corrected sourced rows:

- Ahri    P Essence Theft heals 35 : 95 by level + 20% AP once per fight
          when 9+ fragments are supplied.
- Illaoi  P tentacle hits heal 5% of the fighter's LIVE missing health.
- Kled    declares no Grievous Wounds (removed V25.14; stale worklist)
          40%-for-3s constants.
- LeeSin  Q prices Sonic Wave + the Resonating Strike recast (Min/Max
          Physical Damage rows interpolated by target missing health).
- Naafiri Q prices the recast bonus (Min/Max Bonus Physical Damage rows)
          and heals 45 : 105 + 40% bonus AD once per Q cast; E prices
          dash + Flurry explosion.
- Pantheon Q prices Hurl + Mortal Will empowered term, with the <20%-HP
          execute and R edge rows exposed via options; W prices its
          %max-HP physical damage row.
- Renata  P Leverage procs 1% : 2% (+2% per 100 AP) max-HP magic damage;
          E grants Renata herself the sourced Shield Strength.
- Sion    E applies the sourced 25% armor reduction for 4s after its own
          hit.
- Smolder Q scales with critical strike chance (0% : 75% + 0% : 22.5%)
          and the tier-3 225-stack burn rides Q as true damage.
- Urgot   W prices all 12 shots at the fixed 3.0 attack speed; P legs
          deal per-level % AD + %max-HP; R documents the sub-25%
          execution boundary.

Expected totals are recomputed from data/champions.json leveling rows via
``extract_named``/``extract_value`` against the fight's own stats and the
sourced target health, so every asserted number traces to the cache.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.data_fetcher import get_champion
from src.calculator.healing_reduction import (
    champion_grievous_wound_sources,
)

_DATA = json.loads(
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("data", "champions.json")
    .read_text(encoding="utf-8")
)
_DATA_BY_NAME = {
    str(value.get("name", "")): value
    for value in _DATA.values()
    if isinstance(value, dict)
}

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

# Unit-level parse context: level 18, no items (0 bonus AD / AP / crit).
_PARSE_STATS = {
    "attack_damage": 130.0,
    "base_attack_damage": 60.0,
    "bonus_attack_damage": 0.0,
    "ability_power": 0.0,
    "health": 2_000.0,
    "bonus_health": 0.0,
    "critical_strike_chance": 0.0,
}
_PARSE_TARGET = {
    "target_max_health": 2_000.0,
    "target_current_health": 2_000.0,
    "target_missing_health": 0.0,
}


def _fight(
    champion: str,
    *,
    duration: float = 10.0,
    options: dict | None = None,
    target_health: float = 2000.0,
    armor: float = 0.0,
    mr: float = 0.0,
    items: list[str] | None = None,
    enemies: list[dict] | None = None,
    one_rotation: bool = False,
) -> dict:
    """One /api/calculate fight; default level 18, 0 resists, no items."""
    payload: dict = {
        "champion": champion,
        "level": 18,
        "items": items or [],
        "role": "top",
        "fight_mode": "one_rotation" if one_rotation else "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "ability_ranks": _RANKS,
        "champion_options": options or {},
        "target_health": target_health,
        "target_armor": armor,
        "target_mr": mr,
    }
    if enemies is not None:
        payload["enemies"] = enemies
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _main_sources(data: dict) -> dict[str, float]:
    """Per-ability fight damage by ability name (either response shape)."""
    combat = data.get("combat") or {}
    participants = combat.get("breakdown")
    if isinstance(participants, list):
        for participant in participants:
            if participant.get("participant_id") == "main":
                return {
                    source["name"]: source["total_damage"]
                    for source in participant.get("sources", [])
                }
    # Bare-target response: the top-level breakdown is the main-only dict.
    return {
        entry["name"]: entry["total_damage"]
        for entry in data.get("breakdown", {}).values()
        if isinstance(entry, dict) and entry.get("name")
    }


def _main_heals(data: dict, source: str) -> list[dict]:
    """Main-owned heal events (either response shape)."""
    combat = data.get("combat") or {}
    if combat.get("healing_events"):
        return [
            event
            for event in combat["healing_events"]
            if event.get("attacker") == "main" and event.get("source") == source
        ]
    return [
        event
        for event in data.get("self_healing_events", [])
        if event.get("source") == source
    ]


def _parse(champion: str, options: dict | None = None):
    """Parse abilities at level 18 with the shared no-item stat context."""
    return parse_champion_abilities(
        _DATA_BY_NAME[champion],
        18,
        0.0,
        ability_ranks=_RANKS,
        champion_options=options or {},
        champion_stats=dict(_PARSE_STATS),
        target_stats=dict(_PARSE_TARGET),
    )


def _resolve(champion: str, slot: str, attr: str, rank: int) -> float:
    """Resolve one cached leveling row at rank against the parse context."""
    ability = _DATA_BY_NAME[champion]["abilities"][slot][0]
    return extract_named(ability, attr, rank, dict(_PARSE_STATS), dict(_PARSE_TARGET))


def _ability(champion: str, slot: str) -> dict:
    return _DATA_BY_NAME[champion]["abilities"][slot][0]


def _fight_stats(data: dict) -> dict:
    return data["champion_stats"]


def _hunting_stats() -> dict:
    """``_PARSE_STATS`` with Naafiri's W hunt bonus AD already folded in.

    The Call of the Pack grants "20% AD bonus attack damage" as a
    BUFF-phase ``stat_buff``, so every bonus-AD ratio on Q/E/R parses
    against the buffed stat.  A direct parse call has no fight window,
    which is the per-cast model — the whole 20%.
    """
    stats = dict(_PARSE_STATS)
    bonus = 0.20 * stats["attack_damage"]
    stats["bonus_attack_damage"] += bonus
    stats["attack_damage"] += bonus
    return stats


# ---------------------------------------------------------------------------
# Ahri — P Essence Theft (9-fragment heal)
# ---------------------------------------------------------------------------


class TestAhriEssenceTheft:
    def test_essence_theft_heals_leveled_amount_once_per_fight(self):
        """P: 9 fragments consumed -> 35 : 95 by level (+ 20% AP)."""
        data = _fight("Ahri")
        heals = _main_heals(data, "Essence Theft")
        assert heals, "Essence Theft heal missing"
        assert len(heals) == 1
        assert heals[0]["amount"] == pytest.approx(95.0, abs=0.06)

    def test_essence_theft_requires_nine_fragments(self):
        """Below 9 fragments the module emits no P receipt and no heal."""
        data = _fight("Ahri", options={"p_essence_fragments": 8})
        assert not _main_heals(data, "Essence Theft")

    def test_q_remains_two_pass_damage(self):
        """Q still prices the magic-outgoing + true-returning two passes."""
        abilities = _parse("Ahri")
        q = abilities["Q"]
        assert [part.damage_type for part in q["parts"]] == ["magic", "true"]
        assert q["total_raw"] == pytest.approx(
            _resolve("Ahri", "Q", "Damage Per Pass", 5) * 2
        )


# ---------------------------------------------------------------------------
# Illaoi — P tentacle hits heal 5% of live missing health
# ---------------------------------------------------------------------------


class TestIllaoiTentacleHeal:
    def test_tentacle_heal_is_five_percent_of_live_missing_health(self):
        """Each tentacle champion hit heals 5% of the LIVE missing health."""
        data = _fight(
            "Illaoi",
            options={"p_tentacles": 3},
            enemies=[
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "role": "mid",
                    "ability_ranks": _RANKS,
                }
            ],
        )
        heals = _main_heals(data, "Prophet of an Elder God")
        assert len(heals) == 3
        max_health = next(
            p["survival"]["max_health"]
            for p in data["combat"]["participants"]
            if p["participant_id"] == "main"
        )
        incoming = [
            float(event["damage"])
            for event in data["combat"]["events"]
            if event.get("attacker") != "main" and event.get("target") == "main"
        ]
        incoming_times = [
            float(event["time"])
            for event in data["combat"]["events"]
            if event.get("attacker") != "main" and event.get("target") == "main"
        ]
        assert all(heal["raw_amount"] > 0.0 for heal in heals)
        assert all(heal["raw_amount"] <= 0.05 * max_health + 0.06 for heal in heals)
        # Replay the ledger: health = max - damage(<=t) + heals(<t); the
        # heal's raw amount is 5% of the missing health at that instant.
        for index, heal in enumerate(heals):
            heal_time = float(heal["time"])
            damage_up_to = sum(
                amount
                for time, amount in zip(incoming_times, incoming)
                if time <= heal_time + 1e-9
            )
            heals_before = sum(
                float(h.get("raw_amount", h.get("amount", 0.0))) for h in heals[:index]
            )
            missing = max_health - (max_health - damage_up_to + heals_before)
            assert heal["raw_amount"] == pytest.approx(0.05 * missing, abs=0.3)

    def test_tentacle_damage_prices_sourced_row(self):
        """P damage stays the sourced Bonus Physical Damage row x count."""
        data = _fight("Illaoi", target_health=2000)
        sources = _main_sources(data)
        per_strike = extract_named(
            _ability("Illaoi", "P"), "Bonus Physical Damage", 18, _fight_stats(data), {}
        )
        q_increase = extract_value(_ability("Illaoi", "Q"), "Damage Increase", 5)
        expected = per_strike * (1.0 + q_increase / 100.0)
        assert sources["Prophet of an Elder God"] == pytest.approx(expected, abs=0.11)


# ---------------------------------------------------------------------------
# Kled — Q (Pocket Pistol) Grievous Wounds
# ---------------------------------------------------------------------------


class TestKledGrievousWounds:
    def test_kled_declares_no_wound_source(self):
        """Kled's wound was removed in V25.14 — no Q source may be declared.

        The e8-interactions worklist entry is stale; the wiki cache carries
        no Grievous Wounds on either Q entry (autoresearch pass 11).
        """
        kled = get_champion("Kled")
        assert champion_grievous_wound_sources(kled) == ()

    def test_q_hit_does_not_wound_enemy_self_healer(self):
        """A Q hit must not reduce Aatrox's healing (no wound to apply)."""
        data = _fight(
            "Kled",
            enemies=[
                {
                    "champion": "Aatrox",
                    "level": 18,
                    "items": [],
                    "role": "top",
                    "ability_ranks": _RANKS,
                }
            ],
        )
        enemy = next(
            p
            for p in data["combat"]["participants"]
            if p["participant_id"].startswith("enemy")
        )
        survival = enemy["survival"]
        assert survival["healing_reduced"] == 0.0
        assert not any(
            "Kled" in event.get("sources", [])
            for event in survival["healing_reduction_events"]
        )


# ---------------------------------------------------------------------------
# LeeSin — Q Sonic Wave + Resonating Strike recast
# ---------------------------------------------------------------------------


class TestLeeSinQRecast:
    def test_q_prices_sonic_wave_plus_resonating_strike(self):
        """Q1 (Sonic Wave) + Q2 recast interpolated by missing health."""
        abilities = _parse("Lee Sin")
        q = abilities["Q"]
        assert len(q["parts"]) == 2
        sonic = extract_named(
            _ability("Lee Sin", "Q"), "Physical Damage", 5, dict(_PARSE_STATS), {}
        )
        recast_min = extract_named(
            _DATA_BY_NAME["Lee Sin"]["abilities"]["Q"][1],
            "Minimum Physical Damage",
            5,
            dict(_PARSE_STATS),
            {},
        )
        assert q["parts"][0].amount == pytest.approx(sonic)
        assert q["parts"][1].hp_scaled_damage is not None
        assert q["total_raw"] == pytest.approx(sonic + recast_min)

    def test_q_fight_bounds_and_event_count(self):
        """The fight prices 2 events per cast between the min/max bounds."""
        data = _fight("Lee Sin")
        row = data["breakdown"]["Q"]
        casts = int(row["casts"])
        sonic = extract_named(
            _ability("Lee Sin", "Q"), "Physical Damage", 5, _fight_stats(data), {}
        )
        recast_min = extract_named(
            _DATA_BY_NAME["Lee Sin"]["abilities"]["Q"][1],
            "Minimum Physical Damage",
            5,
            _fight_stats(data),
            {},
        )
        recast_max = extract_named(
            _DATA_BY_NAME["Lee Sin"]["abilities"]["Q"][1],
            "Maximum Physical Damage",
            5,
            _fight_stats(data),
            {},
        )
        assert row["total_damage"] >= (sonic + recast_min) * casts - 1e-6
        assert row["total_damage"] <= (sonic + recast_max) * casts + 1e-6
        events = [
            e
            for e in data["damage_events"]
            if e.get("source", e.get("source_key")) == "Q" and e.get("damage", 0.0) > 0
        ]
        assert len(events) == 2 * casts

    def test_q_without_recast_prices_sonic_wave_only(self):
        data = _fight("Lee Sin", options={"q_recast": False})
        row = data["breakdown"]["Q"]
        casts = int(row["casts"])
        sonic = extract_named(
            _ability("Lee Sin", "Q"), "Physical Damage", 5, _fight_stats(data), {}
        )
        assert row["total_damage"] == pytest.approx(sonic * casts)


# ---------------------------------------------------------------------------
# Naafiri — Q recast bonus + heal, E dash + Flurry
# ---------------------------------------------------------------------------


class TestNaafiriQRecastAndE:
    def test_q_prices_initial_ticks_and_recast_bonus(self):
        abilities = _parse("Naafiri")
        q = abilities["Q"]
        assert len(q["parts"]) == 3
        # Every row below carries a bonus-AD ratio, and W's hunt is a
        # BUFF-phase bonus-AD grant that parses before Q.
        hunting = _hunting_stats()
        initial = extract_named(
            _ability("Naafiri", "Q"),
            "Initial Physical Damage",
            5,
            hunting,
            {},
        )
        per_tick = extract_named(
            _ability("Naafiri", "Q"),
            "Bleed Physical Damage per Tick",
            5,
            hunting,
            {},
        )
        recast_min = extract_named(
            _ability("Naafiri", "Q"),
            "Minimum Bonus Physical Damage",
            5,
            hunting,
            {},
        )
        assert q["total_raw"] == pytest.approx(initial + per_tick * 10 + recast_min)

    def test_q_heals_once_per_cast(self):
        """The recast against a champion heals 45 : 105 + 40% bonus AD."""
        data = _fight("Naafiri")
        heals = _main_heals(data, "Darkin Daggers")
        casts = int(data["breakdown"]["Q"]["casts"])
        assert len(heals) == casts
        expected = extract_named(
            _ability("Naafiri", "Q"), "Heal", 5, _fight_stats(data), {}
        )
        assert all(
            heal["amount"] == pytest.approx(expected, abs=0.06) for heal in heals
        )

    def test_e_prices_dash_plus_flurry(self):
        abilities = _parse("Naafiri")
        e = abilities["E"]
        hunting = _hunting_stats()
        dash = extract_named(
            _ability("Naafiri", "E"), "Dash Physical Damage", 5, hunting, {}
        )
        flurry = extract_named(
            _ability("Naafiri", "E"),
            "Flurry Physical Damage",
            5,
            hunting,
            {},
        )
        assert e["total_raw"] == pytest.approx(dash + flurry)
        # The fight's own stats already carry W's hunt bonus, weighted by
        # the share of the 10-second window its 5 seconds cover.
        data = _fight("Naafiri")
        fight_stats = _fight_stats(data)
        fight_dash = extract_named(
            _ability("Naafiri", "E"), "Dash Physical Damage", 5, fight_stats, {}
        )
        fight_flurry = extract_named(
            _ability("Naafiri", "E"), "Flurry Physical Damage", 5, fight_stats, {}
        )
        casts = int(data["breakdown"]["E"]["casts"])
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(
            (fight_dash + fight_flurry) * casts, abs=0.06
        )


# ---------------------------------------------------------------------------
# Pantheon — Q execute + Mortal Will, W %max-HP, R edge row
# ---------------------------------------------------------------------------


class TestPantheonRows:
    def test_q_prices_hurl_plus_mortal_will(self):
        abilities = _parse("Pantheon")
        hurl = extract_named(
            _ability("Pantheon", "Q"), "Hurl Physical Damage", 5, dict(_PARSE_STATS), {}
        )
        mortal_will = extract_value(_ability("Pantheon", "Q"), "Per-Level Scaling", 18)
        assert abilities["Q"]["total_raw"] == pytest.approx(hurl + mortal_will)

    def test_q_execute_uses_increased_hurl_row(self):
        abilities = _parse("Pantheon", options={"q_execute": True})
        increased = extract_named(
            _ability("Pantheon", "Q"),
            "Increased Hurl Damage",
            5,
            dict(_PARSE_STATS),
            {},
        )
        mortal_will = extract_value(_ability("Pantheon", "Q"), "Per-Level Scaling", 18)
        assert abilities["Q"]["total_raw"] == pytest.approx(increased + mortal_will)

    def test_w_prices_max_health_physical_damage(self):
        """W is %max-HP physical damage (6-8% + per-100 AP/bonus health)."""
        abilities = _parse("Pantheon")
        percent = extract_value(_ability("Pantheon", "W"), "Physical Damage", 5, 0)
        assert abilities["W"]["total_raw"] == pytest.approx(percent / 100.0 * 2000.0)
        data = _fight("Pantheon", target_health=2000)
        casts = int(data["breakdown"]["W"]["casts"])
        assert data["breakdown"]["W"]["total_damage"] == pytest.approx(
            percent / 100.0 * 2000.0 * casts
        )

    def test_r_edge_row_exposed(self):
        abilities = _parse("Pantheon", options={"r_edge": True})
        reduced = extract_named(
            _ability("Pantheon", "R"), "Reduced Damage", 3, dict(_PARSE_STATS), {}
        )
        assert abilities["R"]["total_raw"] == pytest.approx(reduced)
        assert _parse("Pantheon")["R"]["total_raw"] == pytest.approx(
            extract_named(
                _ability("Pantheon", "R"), "Magic Damage", 3, dict(_PARSE_STATS), {}
            )
        )


# ---------------------------------------------------------------------------
# Renata — P Leverage on-hit, E Loyalty Program self-shield
# ---------------------------------------------------------------------------


class TestRenataLeverageAndShield:
    def test_leverage_on_hit_procs_max_hp_magic_damage(self):
        abilities = _parse("Renata Glasc")
        passive = abilities["passive"]
        percent = extract_value(
            _ability("Renata Glasc", "P"), "Per-Level Scaling", 18, 0
        )
        per_proc = percent / 100.0 * 2000.0
        assert passive["proc_count"] == 1
        assert passive["total_raw"] == pytest.approx(per_proc)
        data = _fight("Renata Glasc", target_health=2000)
        assert data["breakdown"]["passive"]["total_damage"] == pytest.approx(per_proc)

    def test_e_grants_self_shield_with_sourced_strength(self):
        """'Renata and allies struck are granted a shield' — self included."""
        data = _fight(
            "Renata Glasc",
            enemies=[
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "role": "mid",
                    "ability_ranks": _RANKS,
                }
            ],
        )
        shields = [
            e
            for e in data["combat"]["support_events"]
            if e.get("kind") == "shield"
            and e.get("attacker") == "main"
            and e.get("recipient") == "main"
        ]
        assert shields, "Loyalty Program self-shield missing"
        expected = extract_named(
            _ability("Renata Glasc", "E"),
            "Shield Strength",
            5,
            _fight_stats(data),
            {},
        )
        assert shields[0]["amount"] == pytest.approx(expected)
        assert shields[0]["applied_amount"] == pytest.approx(expected)
        assert shields[0]["source"] == "Loyalty Program"


# ---------------------------------------------------------------------------
# Sion — E Roar of the Slayer 25% armor reduction
# ---------------------------------------------------------------------------


class TestSionArmorReduction:
    def test_e_carries_25_percent_armor_reduction_for_four_seconds(self):
        abilities = _parse("Sion")
        assert abilities["E"]["target_debuff"] == {
            "armor_reduction_percent": 25.0,
            "duration": 4.0,
        }

    def test_post_e_physical_damage_benefits_from_the_shred(self):
        """F3 shred-first: E opens the rotation, so Q and R both mitigate
        at the 25%-shredded armor (100 -> 75)."""
        data = _fight("Sion", armor=100, one_rotation=True)
        assert data["effective_armor"] == pytest.approx(75.0)
        # E (Roar of the Slayer) now opens the burst — its 25% armor
        # reduction shred lands BEFORE Q, so Q mitigates at 75 armor.
        q_raw = 350.0 + 2.4 * float(data["champion_stats"]["attack_damage"])
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            q_raw * 100.0 / 175.0, abs=0.11
        )
        # R resolves after the shred: 1200 + 120% bonus AD at 75 armor.
        r_raw = 1200.0 + 1.2 * float(data["champion_stats"]["bonus_attack_damage"])
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(
            r_raw * 100.0 / 175.0, abs=0.11
        )


# ---------------------------------------------------------------------------
# Smolder — Q crit scaling + tier-3 225-stack burn
# ---------------------------------------------------------------------------


class TestSmolderCritAndBurn:
    def test_q_scales_with_critical_strike_chance(self):
        abilities = _parse("Smolder")
        q = abilities["Q"]
        base = q["total_raw"] - _burn_for(2000.0, 225)
        assert q["parts"][0].amount == pytest.approx(base)
        # 15% crit -> 1 + 0.975 x 0.15 multiplier on the physical part.
        crit_stats = dict(_PARSE_STATS)
        crit_stats["critical_strike_chance"] = 15.0
        abilities15 = parse_champion_abilities(
            _DATA_BY_NAME["Smolder"],
            18,
            0.0,
            ability_ranks=_RANKS,
            champion_options={"p_stacks": 0},
            champion_stats=crit_stats,
            target_stats=dict(_PARSE_TARGET),
        )
        assert abilities15["Q"]["parts"][0].amount == pytest.approx(
            base * (1.0 + 0.975 * 0.15)
        )

    def test_tier3_burn_rides_q_as_true_damage(self):
        """225 stacks: 2.5% per 100 bAD + 0.5% per 100 stacks of max HP."""
        data = _fight("Smolder", target_health=2000)
        burn_row = data["breakdown"]["dragon_practice_burn"]
        q_casts = int(data["breakdown"]["Q"]["casts"])
        expected_per_hit = 2000.0 * (0.5 * 225 / 100.0 / 100.0)
        assert burn_row["total_damage"] == pytest.approx(expected_per_hit * q_casts)
        assert burn_row["count"] == q_casts
        assert "true damage" in burn_row["detail"]

    def test_p_documents_the_tier3_boundary(self):
        abilities = _parse("Smolder")
        assert "225" in abilities["passive"]["detail"]
        assert "burn" in abilities["passive"]["detail"].lower()


def _burn_for(target_max: float, stacks: int) -> float:
    """Tier-3 burn total at 0 bonus AD: 0.5% per 100 stacks of max HP."""
    return target_max * (0.5 * stacks / 100.0 / 100.0)


# ---------------------------------------------------------------------------
# Urgot — W 12-shot Purge, P Echoing Flames legs, R execute boundary
# ---------------------------------------------------------------------------


class TestUrgotPurge:
    def test_w_prices_twelve_shots_at_three_point_zero_as(self):
        abilities = _parse("Urgot")
        w = abilities["W"]
        assert w["parts"][0].count == 12
        data = _fight("Urgot")
        per_shot = extract_named(
            _ability("Urgot", "W"),
            "Modified Physical Damage",
            5,
            _fight_stats(data),
            {},
        )
        assert w["parts"][0].amount == pytest.approx(
            extract_named(
                _ability("Urgot", "W"),
                "Modified Physical Damage",
                5,
                dict(_PARSE_STATS),
                {},
            )
        )
        casts = int(data["breakdown"]["W"]["casts"])
        assert data["breakdown"]["W"]["total_damage"] == pytest.approx(
            per_shot * 12 * casts, abs=0.11
        )

    def test_p_legs_deal_per_level_ad_plus_max_hp(self):
        abilities = _parse("Urgot")
        passive = abilities["passive"]
        ad_percent = extract_value(_ability("Urgot", "P"), "Per-Level Scaling", 18, 0)
        hp_percent = extract_value(_ability("Urgot", "P"), "Max Health Damage", 18, 0)
        per_proc = ad_percent / 100.0 * 130.0 + hp_percent / 100.0 * 2000.0
        assert passive["proc_count"] == 1
        assert passive["total_raw"] == pytest.approx(per_proc)
        data = _fight("Urgot")
        per_proc_fight = (
            ad_percent / 100.0 * float(data["champion_stats"]["attack_damage"])
            + hp_percent / 100.0 * 2000.0
        )
        assert data["breakdown"]["passive"]["total_damage"] == pytest.approx(
            per_proc_fight
        )

    def test_r_documents_execution_boundary(self):
        abilities = _parse("Urgot")
        assert "execution" in abilities["R"]["detail"].lower()
        assert abilities["R"]["total_raw"] == pytest.approx(
            extract_named(
                _ability("Urgot", "R"), "Physical Damage", 3, dict(_PARSE_STATS), {}
            )
        )
