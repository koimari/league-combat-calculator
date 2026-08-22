"""P1-3: zero-review closures — Briar, Kindred, Lux, Mel, Neeko, Riven,
Skarner, Varus, Vladimir, Zac.

Every champion that carried a CP-era "review" verdict now prices its
remaining sourced mechanic deterministically.  This suite drives
/api/calculate fights at level 18 (basic abilities rank 5, R rank 3, no
items, target armor/MR 0) and asserts per-slot totals against values
recomputed from the cached data/champions.json leveling rows plus the
fight's own stats (the E2/E3 pattern).  Support shields and
self-healing receipts are asserted from the roster ledger (enemy fights)
because those events are authored by the participant timeline.

New options and their probes:
- Kindred w_hunters_vigor_stacks  (100 = next-auto heal receipt)
- Lux      p_illumination_procs   (procs of the post-ability mark consume)
- Riven    (R1 bonus-AD buff priced via an AD item probe)
- Varus    w_active_empower / target_missing_hp_pct
- Vladimir r_hemoplague_debuff    (on/off probe)
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.data_fetcher import get_champion

_DATA = json.loads(
    Path(__file__).resolve().parents[1].joinpath("data", "champions.json").read_text()
)

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_ROUNDING_TOLERANCE = 0.6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(champion, *, level=18, options=None, stats=None, ranks=_RANKS):
    """Parse a module against the fight's own stat context."""
    data = get_champion(champion)
    base = {
        "ability_power": 0.0,
        "health": 2000.0,
        "attack_damage": 100.0,
        "bonus_attack_damage": 0.0,
    }
    if stats:
        base.update(stats)
    return parse_champion_abilities(
        data,
        level,
        base["ability_power"],
        ability_ranks=ranks,
        champion_stats=base,
        champion_options=options or {},
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
    )


def _fight(
    champion,
    *,
    options=None,
    cast_order=None,
    mode="one_rotation",
    duration=10.0,
    include_autos=False,
    enemy=None,
):
    """One /api/calculate fight, level 18, rank 5 / R 3, no items.

    With ``enemy=None`` the fight runs against the default dummy target
    (target_health 2000, armor/MR 0) so post-mitigation damage equals the
    raw wiki values and per-slot breakdown totals are exact.
    """
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "top",
        "ability_ranks": dict(_RANKS),
        "fight_mode": mode,
        "fight_duration": duration,
        "include_auto_attacks": include_autos,
        "champion_options": options or {},
        "target_health": 2000.0,
        "target_armor": 0,
        "target_mr": 0,
    }
    if enemy is not None:
        payload["enemies"] = [enemy]
    if cast_order is not None:
        payload["cast_order"] = cast_order
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


_ENEMY = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
}


def _slot_total(data, key):
    row = data["breakdown"].get(key)
    assert row is not None, f"breakdown row {key!r} missing"
    return float(row["total_damage"])


def _ability(champion, slot):
    return _DATA[champion]["abilities"][slot][0]


def _expected(champion, slot, attr, rank, stats, target):
    """Resolve one cached leveling row against the fight's own stats."""
    return extract_named(_ability(champion, slot), attr, rank, stats, target)


def _fight_stats(data):
    return dict(data["champion_stats"])


def _target_stats(data):
    max_health = float(data["target_effective_max_health"])
    return {
        "target_max_health": max_health,
        "target_current_health": max_health,
        "target_missing_health": 0.0,
    }


def _main_heals(data, source):
    # Enemy fights enrich heals under combat.healing_events (raw_amount);
    # no-enemy fights report them at the top level (self_healing_events).
    events = data["combat"].get("healing_events")
    if not events:
        events = [
            dict(heal, attacker="main")
            for heal in (data.get("self_healing_events") or [])
        ]
    return [
        heal
        for heal in events
        if heal.get("source") == source and heal.get("attacker", "main") == "main"
    ]


def _main_shields(data, source_startswith):
    return [
        event
        for event in data["combat"].get("support_events", [])
        if event.get("kind") == "shield"
        and str(event.get("source", "")).startswith(source_startswith)
    ]


# ---------------------------------------------------------------------------
# Briar — P bleed heal, Snack Attack heal, R life steal (healing.py)
# ---------------------------------------------------------------------------


class TestBriar:
    """P1-3: the E1-b6 E heal is joined by the sourced P/W/R heal family."""

    def test_ability_damage_unchanged(self):
        """Q/W/E/R damage packets keep their sourced values."""
        data = _fight("Briar")
        stats = _fight_stats(data)
        target = _target_stats(data)
        assert _slot_total(data, "Q") == pytest.approx(
            _expected("Briar", "Q", "Physical Damage", 5, stats, target)
        )
        assert _slot_total(data, "E") == pytest.approx(
            _expected("Briar", "E", "Maximum Magic Damage", 5, stats, target)
        )
        assert _slot_total(data, "R") == pytest.approx(
            _expected("Briar", "R", "Magic Damage", 3, stats, target)
        )

    def test_bleed_self_heal_is_25_percent_of_bleed_damage(self):
        """'The bleed always heals Briar for 25% of the pre-mitigation
        damage dealt' (cached P prose): every bleed tick pays 25% of its
        pre-mitigation amount."""
        data = _fight("Briar", mode="time_based", duration=6, include_autos=True)
        bleed_raw = sum(
            float(event["damage"])
            for event in data["damage_events"]
            if event.get("source") == "stacking_dot_passive"
        )
        heals = _main_heals(data, "Crimson Curse")
        assert len(heals) >= 5
        assert sum(float(h["amount"]) for h in heals) == pytest.approx(
            0.25 * bleed_raw, abs=_ROUNDING_TOLERANCE
        )

    def test_snack_attack_heal_is_5_percent_max_health_plus_heal_percent(self):
        """Snack Attack heals 5% of max health + the sourced Heal
        Percentage (40% at rank 5) of the bite's post-mitigation damage."""
        data = _fight("Briar", mode="time_based", duration=6, include_autos=True)
        w_event = next(
            event for event in data["damage_events"] if event.get("source") == "W"
        )
        heal = _main_heals(data, "Snack Attack")
        assert len(heal) == 1
        expected = 0.05 * float(data["champion_stats"]["health"]) + 0.40 * float(
            w_event["damage"]
        )
        assert float(heal[0]["amount"]) == pytest.approx(expected, abs=0.11)

    def test_r_life_steal_heals_from_basic_attacks(self):
        """Certain Death grants 20% life steal at rank 3; autos heal for
        that share of their post-mitigation damage."""
        data = _fight("Briar", mode="time_based", duration=6, include_autos=True)
        auto_events = [
            event
            for event in data["damage_events"]
            if event.get("source") == "auto_attacks" and event.get("damage") > 0
        ]
        heals = _main_heals(data, "Certain Death")
        assert len(heals) == len(auto_events)
        assert sum(float(h["amount"]) for h in heals) == pytest.approx(
            0.20 * sum(float(e["damage"]) for e in auto_events), abs=0.6
        )


# ---------------------------------------------------------------------------
# Kindred — W Hunter's Vigor (100-stack next-auto heal)
# ---------------------------------------------------------------------------


class TestKindred:
    """P1-3: Hunter's Vigor heal receipt + the missing-health-scaled heal."""

    def test_hunters_vigor_receipt_only_at_100_stacks(self):
        """The W_vigor receipt is emitted only at the sourced 100-stack cap."""
        at_100 = _parse("Kindred", options={"w_hunters_vigor_stacks": 100})
        assert "W_vigor" in at_100
        at_99 = _parse("Kindred", options={"w_hunters_vigor_stacks": 99})
        assert "W_vigor" in at_99  # emitted as an explicit state row
        assert at_99["W_vigor"]["total_raw"] == 0.0

    def test_heal_fires_on_first_auto_scaled_by_missing_health(self):
        """At 100 stacks the next basic attack heals the missing-health
        share of 47 : 81 (based on level) — 81 at level 18."""
        data = _fight(
            "Kindred",
            mode="time_based",
            duration=6,
            include_autos=True,
            enemy=_ENEMY,
        )
        heals = _main_heals(data, "Hunter's Vigor")
        assert len(heals) == 1
        raw = float(heals[0].get("raw_amount", heals[0].get("amount", 0.0)))
        assert 0.0 < raw <= 81.0 + 0.6
        assert raw > 0.0  # the fight's own incoming damage creates missing health

    def test_wolf_frenzy_damage_keeps_sourced_row(self):
        """W damage stays the sourced Magic Damage row over w_attacks."""
        data = _fight("Kindred")
        stats = _fight_stats(data)
        target = _target_stats(data)
        per = extract_named(_ability("Kindred", "W"), "Magic Damage", 5, stats, target)
        assert _slot_total(data, "W") == pytest.approx(per * 3, abs=_ROUNDING_TOLERANCE)


# ---------------------------------------------------------------------------
# Lux — P Illumination procs + W Prismatic Barrier (double) shield
# ---------------------------------------------------------------------------


class TestLux:
    """P1-3: the P proc and the W two-stack shield join the packet."""

    def test_illumination_procs_price_sourced_per_level_damage(self):
        """P: 30 : 200 (based on level) + 35% AP per proc, default 3 procs."""
        data = _fight("Lux")
        stats = _fight_stats(data)
        per_proc = extract_named(
            _ability("Lux", "P"), "Per-Level Scaling", 18, stats, _target_stats(data)
        )
        assert per_proc == pytest.approx(200.0)
        row = data["breakdown"]["passive"]
        assert row["count"] == 3
        assert float(row["total_damage"]) == pytest.approx(per_proc * 3)

    def test_illumination_procs_option_probe(self):
        """p_illumination_procs=1 prices exactly one proc."""
        data = _fight("Lux", options={"p_illumination_procs": 1})
        stats = _fight_stats(data)
        per_proc = extract_named(
            _ability("Lux", "P"), "Per-Level Scaling", 18, stats, _target_stats(data)
        )
        assert _slot_total(data, "passive") == pytest.approx(per_proc)

    def test_w_prismatic_barrier_shields_maximum_shield(self):
        """W shields Lux for the sourced Maximum Shield (throw + return)."""
        data = _fight("Lux", mode="time_based", duration=6, enemy=_ENEMY)
        rows = _main_shields(data, "Prismatic Barrier")
        assert len(rows) == 1
        expected = extract_named(
            _ability("Lux", "W"), "Maximum Shield", 5, _fight_stats(data), {}
        )
        assert rows[0]["amount"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Mel — Q full volley + E field DoT
# ---------------------------------------------------------------------------


class TestMel:
    """P1-3: Q prices the full 6-10 bolt volley; E prices the field DoT."""

    def test_q_prices_initial_plus_subsequent_bolts(self):
        """Q: Initial Explosion + (Number of Bolts - 1) x Subsequent ==
        the wiki's Total Magic Damage row."""
        data = _fight("Mel")
        stats = _fight_stats(data)
        target = _target_stats(data)
        total = extract_named(
            _ability("Mel", "Q"), "Total Magic Damage", 5, stats, target
        )
        assert total == pytest.approx(277.0)
        assert _slot_total(data, "Q") == pytest.approx(total, abs=_ROUNDING_TOLERANCE)

    def test_e_prices_orb_plus_four_field_ticks(self):
        """E: orb + 4 field ticks (game-file DoTDuration 0.5s x 8/s)."""
        data = _fight("Mel")
        stats = _fight_stats(data)
        target = _target_stats(data)
        orb = extract_named(_ability("Mel", "E"), "Orb Magic Damage", 5, stats, target)
        per_tick = extract_named(
            _ability("Mel", "E"), "Field Magic Damage per Tick", 5, stats, target
        )
        assert _slot_total(data, "E") == pytest.approx(orb + 4 * per_tick)

    def test_r_overwhelm_stacks_option_probe(self):
        """r_overwhelm_stacks scales the R per-stack term (probe)."""
        data = _fight("Mel", options={"r_overwhelm_stacks": 5})
        stats = _fight_stats(data)
        flat = extract_named(_ability("Mel", "R"), "Magic Damage", 3, stats, {})
        per_stack = extract_value(_ability("Mel", "R"), "Magic Damage", 3, 2)
        assert _slot_total(data, "R") == pytest.approx(flat + per_stack * 5)


# ---------------------------------------------------------------------------
# Neeko — Q three-burst chain + R Pop Blossom shield
# ---------------------------------------------------------------------------


class TestNeeko:
    """P1-3: Q re-blooms and the game-file R shield."""

    def test_q_prices_initial_plus_two_reblooms(self):
        """Q: Initial + 2 x Subsequent == the Total Maximum Magic Damage."""
        data = _fight("Neeko")
        stats = _fight_stats(data)
        target = _target_stats(data)
        total = extract_named(
            _ability("Neeko", "Q"), "Total Maximum Magic Damage", 5, stats, target
        )
        assert total == pytest.approx(530.0)
        assert _slot_total(data, "Q") == pytest.approx(total, abs=_ROUNDING_TOLERANCE)

    def test_r_shield_prices_game_file_amount(self):
        """R shield: ShieldAmount + ShieldPerChampion (1 nearby enemy) +
        115% AP, 2s (neeko.bin.json NeekoR)."""
        data = _fight("Neeko", mode="time_based", duration=6, enemy=_ENEMY)
        rows = _main_shields(data, "Pop Blossom")
        assert len(rows) == 1
        # rank 3: 175 + 80 (+ 75% + 40% AP) == 255 at 0 AP
        assert rows[0]["amount"] == pytest.approx(255.0)


# ---------------------------------------------------------------------------
# Riven — R1 Blade of the Exile bonus-AD buff
# ---------------------------------------------------------------------------


class TestRiven:
    """P1-3: the R1 AD steroid is expressed and feeds every physical slot."""

    def test_r1_buff_entry_exists_and_scales_bonus_ad(self):
        """The BUFF-phase R_buff entry prices +20% of bonus AD."""
        abilities = _parse("Riven", stats={"bonus_attack_damage": 50.0})
        buff = abilities["R_buff"]
        assert buff["stat_buff"]["bonus_attack_damage"] == pytest.approx(10.0)

    def test_no_item_fight_totals_unchanged(self):
        """At 0 bonus AD the buff is 0, so the no-item burst keeps its
        sourced packet values."""
        data = _fight("Riven")
        assert _slot_total(data, "Q") == pytest.approx(165.0)
        assert _slot_total(data, "W") == pytest.approx(185.0)
        assert _slot_total(data, "R") == pytest.approx(600.0)

    def test_ad_item_probe_buffs_every_physical_slot(self):
        """With a Long Sword (10 AD), R1 adds 20% x 10 == 2 bonus AD and
        Q/W/R scale off it (the ult-window understatement is closed)."""
        data = _fight("Riven", enemy=None)
        payload = {
            "champion": "Riven",
            "level": 18,
            "items": ["Long Sword"],
            "role": "top",
            "ability_ranks": dict(_RANKS),
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "champion_options": {},
            "target_health": 2000.0,
            "target_armor": 0,
            "target_mr": 0,
        }
        response = app_module.app.test_client().post("/api/calculate", json=payload)
        assert response.status_code == 200, response.get_json()
        data = response.get_json()
        stats = dict(data["champion_stats"])
        bonus_ad = float(stats["bonus_attack_damage"])
        assert bonus_ad >= 10.0  # Long Sword
        # The response stats already include the R1 buff (+20% of bonus
        # AD, factored at cast), so the sourced Q row resolves exactly.
        q_expected = extract_named(
            _ability("Riven", "Q"), "Physical Damage", 5, stats, _target_stats(data)
        )
        assert q_expected > 165.0  # the buff raised Q above the 0-bAD base
        assert _slot_total(data, "Q") == pytest.approx(q_expected, abs=0.6)


# ---------------------------------------------------------------------------
# Skarner — W 8%-max-HP shield + E Ixtal's Impact damage
# ---------------------------------------------------------------------------


class TestSkarner:
    """P1-3: W shield and the E formula-slot inconsistency."""

    def test_w_shield_is_8_percent_max_health(self):
        """W shields Skarner for 8% of his maximum health for 2.5s."""
        data = _fight("Skarner", mode="time_based", duration=6, enemy=_ENEMY)
        rows = _main_shields(data, "Seismic Bastion")
        assert len(rows) == 1
        expected = 0.08 * float(_fight_stats(data)["health"])
        assert rows[0]["amount"] == pytest.approx(expected)

    def test_e_prices_terrain_collision_damage(self):
        """E: Physical Damage row (flat + 120% bAD + 6% of Skarner's max
        health) — the formula slot now matches MODULE_COVERAGE."""
        data = _fight("Skarner")
        stats = _fight_stats(data)
        flat = extract_named(_ability("Skarner", "E"), "Physical Damage", 5, stats, {})
        max_hp_pct = extract_value(_ability("Skarner", "E"), "Physical Damage", 5, 2)
        expected = flat + max_hp_pct / 100.0 * float(stats["health"])
        assert _slot_total(data, "E") == pytest.approx(expected, abs=0.6)


# ---------------------------------------------------------------------------
# Varus — W active empowered shot (missing-health magic)
# ---------------------------------------------------------------------------


class TestVarus:
    """P1-3: the W active empower rides the fully-charged Q."""

    def test_q_empower_prices_active_maximum_missing_health(self):
        """Q prices the arrow + 3-stack detonation + the W-active empower
        (Active Maximum Magic Damage = 21% of missing health at W rank 5)."""
        data = _fight("Varus")
        stats = _fight_stats(data)
        target = _target_stats(data)
        arrow = extract_named(
            _ability("Varus", "Q"), "Maximum Physical Damage", 5, stats, target
        )
        per_stack = extract_named(
            _ability("Varus", "W"), "Bonus Magic Damage per Stack", 5, stats, target
        )
        empower_pct = extract_value(
            _ability("Varus", "W"), "Active Maximum Magic Damage", 5
        )
        empower = empower_pct / 100.0 * 0.50 * float(target["target_max_health"])
        assert _slot_total(data, "Q") == pytest.approx(arrow)
        assert _slot_total(data, "blight_detonation") == pytest.approx(
            per_stack * 3 + empower, abs=_ROUNDING_TOLERANCE
        )

    def test_w_active_empower_option_probe(self):
        """w_active_empower=False prices the arrow + detonation only."""
        data = _fight("Varus", options={"w_active_empower": False})
        stats = _fight_stats(data)
        target = _target_stats(data)
        per_stack = extract_named(
            _ability("Varus", "W"), "Bonus Magic Damage per Stack", 5, stats, target
        )
        assert _slot_total(data, "blight_detonation") == pytest.approx(
            per_stack * 3, abs=_ROUNDING_TOLERANCE
        )

    def test_target_missing_hp_pct_option_probe(self):
        """target_missing_hp_pct=100 doubles the empower's missing-health
        base versus 50."""
        data50 = _fight("Varus")
        data100 = _fight("Varus", options={"target_missing_hp_pct": 100})
        assert _slot_total(data100, "blight_detonation") > _slot_total(
            data50, "blight_detonation"
        )


# ---------------------------------------------------------------------------
# Vladimir — R Hemoplague 10% increased-damage-taken
# ---------------------------------------------------------------------------


class TestVladimir:
    """P1-3: the R debuff amplifies every damage entry by 10%."""

    def test_r_debuff_amplifies_all_damage(self):
        """R-first combo: every entry is amplified 10%, so the R
        detonation itself prices the wiki's self-amplified 385."""
        data = _fight("Vladimir", cast_order=["R", "Q", "W", "E"])
        assert _slot_total(data, "R") == pytest.approx(350.0 * 1.1)
        assert _slot_total(data, "Q") == pytest.approx(160.0 * 1.1)
        assert _slot_total(data, "W") == pytest.approx(300.0 * 1.1)

    def test_hemoplague_debuff_option_probe(self):
        """r_hemoplague_debuff=False prices the unmarked rotation."""
        data = _fight("Vladimir", options={"r_hemoplague_debuff": False})
        assert _slot_total(data, "R") == pytest.approx(350.0)
        assert _slot_total(data, "Q") == pytest.approx(160.0)

    def test_sanguine_pool_keeps_four_sourced_ticks(self):
        """The E2 tick certification survives the AMP (4 x 82.5 at rank 5)."""
        data = _fight("Vladimir")
        assert _slot_total(data, "W") == pytest.approx(300.0 * 1.1, abs=0.6)


# ---------------------------------------------------------------------------
# Zac — Q both Stretching Strikes
# ---------------------------------------------------------------------------


class TestZac:
    """P1-3: Q prices both arm strikes (2 x per-hit == Total)."""

    def test_q_prices_both_strikes(self):
        """Q: 2 x the per-hit Magic Damage row == Total Magic Damage."""
        data = _fight("Zac")
        stats = _fight_stats(data)
        total = extract_named(
            _ability("Zac", "Q"), "Total Magic Damage", 5, stats, _target_stats(data)
        )
        assert total == pytest.approx(360.0)
        assert _slot_total(data, "Q") == pytest.approx(total, abs=_ROUNDING_TOLERANCE)
        assert int(data["breakdown"]["Q"]["casts"]) == 1
        # two authored hit events land on the Q row (cast + empowered attack)
        events = data["damage_events"]
        assert len([e for e in events if e.get("phase") == "ability"]) >= 2

    def test_r_keeps_initial_plus_three_bounces(self):
        """R keeps the E2-3 sourced bounce pricing."""
        data = _fight("Zac")
        total = extract_named(
            _ability("Zac", "R"), "Total Magic Damage", 3, _fight_stats(data), {}
        )
        assert total == pytest.approx(650.0)
        assert _slot_total(data, "R") == pytest.approx(total, abs=_ROUNDING_TOLERANCE)
