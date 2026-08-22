"""E3-3: stack/charge/mark systems — batch 3 (12 champions).

Each test drives /api/calculate fights (level 18, rank 5 / R rank 3, no
items) through the app test client, plus parse-level assertions for the
exact sourced values. The sourced numbers are read from
data/champions.json leveling rows (never hardcoded); where a stack value
is wiki prose (no leveling row — Volibear storm AS, Senna Mist, Thresh
souls, Master Yi Double Strike, Xayah Clean Cuts), the module constant
is asserted against the module's documented formula.

Champion coverage:
- KogMaw    R Living Artillery missing-HP amplify (the E3 "execute
            curve"); R stacks are mana-only (+40 per stack, cap 9) and
            are documented as not modeled.
- Volibear  P Relentless Storm: 5 stacks of 5% (+3% per 100 AP) bonus
            AS, Lightning Claws on-hit at 5 stacks; W Wounded 2nd bite
            +50% (+25% per 100 bonus AD).
- Senna     P Absolution: Mist stacks (0.75 AD each, +10% crit per 20)
            plus the Weakened Soul mark (every-2nd-hit % current
            health, priced against max health).
- Thresh    P Damnation: +1 AP and +1 bonus armor per Soul.
- Aurora    P Spirit Abjuration: 3-hit % max-health proc (autos AND
            ability hits stack).
- Katarina  P Voracity/Sinister Steel: dagger-retrieval spin =
            level flat + 60% bonus AD + level-banded AP ratio
            (70/80/90/100% at 1-5/6-10/11-15/16+).
- Xayah     P Clean Cuts stacks feed E Bladecaller's per-Feather
            detonation (7 Feathers expected = 5 empowered autos + 2 Q).
- Zac       no damage-relevant stack mechanic (Goo chunks heal; the
            module documents the boundary).
- Syndra    P Transcendent splinters: 120 -> +15% total AP; 60+ -> W
            bonus true damage; R per-sphere damage.
- MasterYi  P Double Strike: every 3rd auto strikes twice (50% AD).
- Fiora     P Duelist's Dance: vitals are level-scaled true damage.
- Jinx      Q Pow-Pow Rev'd Up (3 stacks of bonus AS) and P Get
            Excited! (25% total AS per takedown stack, max 5).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.stats import calculate_total_stats

_DATA = json.loads(
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("data", "champions.json")
    .read_text(encoding="utf-8")
)

_ENEMY = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

_TARGET_2000 = {"target_max_health": 2000.0, "target_current_health": 2000.0}


def _fight(
    champion: str,
    *,
    fight_mode: str = "one_rotation",
    duration: int = 5,
    options: dict | None = None,
    ranks: dict | None = _FULL_RANKS,
    include_auto_attacks: bool = False,
    role: str = "top",
) -> dict:
    """Run one /api/calculate fight and return the coupled combat ledger."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": role,
        "ability_ranks": ranks,
        "fight_mode": fight_mode,
        "fight_duration": duration,
        "include_auto_attacks": include_auto_attacks,
        "champion_options": options or {},
        "enemies": [_ENEMY],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _main_sources(combat: dict) -> dict[str, float]:
    """Map of source name -> total damage for the main actor."""
    for row in combat["breakdown"]:
        if row.get("participant_id") == "main":
            return {s["name"]: s["total_damage"] for s in row["sources"]}
    raise AssertionError("no main participant in breakdown")


def _main_events(combat: dict, source: str) -> list[dict]:
    """The main actor's events for one source."""
    return [
        e
        for e in combat["events"]
        if e.get("attacker") == "main" and e.get("source") == source
    ]


def _value(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    modifier_index: int = 0,
) -> float:
    """Read one modifier's raw value at rank from data/champions.json."""
    ability = _DATA[champion]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if modifier_index >= len(modifiers):
                return 0.0
            values = modifiers[modifier_index].get("values", [])
            if not values:
                return 0.0
            return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


def _stats(champion: str, *, level: int = 18) -> dict:
    """The app's level-18 no-item stats for one champion."""
    return calculate_total_stats(_DATA[champion], level, [])


def _parse(
    champion: str,
    *,
    ap: float = 0.0,
    options: dict | None = None,
    target: dict | None = _TARGET_2000,
    ranks: dict | None = _FULL_RANKS,
    level: int = 18,
    ad_override: float | None = None,
    bonus_ad_override: float | None = None,
) -> tuple[dict, dict]:
    """Mirror the app pipeline: stats -> parse abilities at level/ranks."""
    stats = _stats(champion, level=level)
    if ad_override is not None:
        stats["attack_damage"] = ad_override
    if bonus_ad_override is not None:
        stats["bonus_attack_damage"] = bonus_ad_override
        stats["attack_damage"] = stats["base_attack_damage"] + bonus_ad_override
    abilities = parse_champion_abilities(
        _DATA[champion],
        level,
        ap,
        ability_ranks=ranks,
        champion_stats=stats,
        target_stats=dict(target),
        champion_options=options or {},
    )
    return stats, abilities


# ---------------------------------------------------------------------------
# Kog'Maw — R Living Artillery missing-HP execute curve (stacks mana-only)
# ---------------------------------------------------------------------------


class TestKogMaw:
    """R: the E3 amplify — damage scales with the target's missing HP."""

    def test_r_rank3_min_and_max_bounds(self) -> None:
        """Rank 3: 180 at full HP -> 360 at >=60% missing, linear between."""
        _, abilities = _parse("KogMaw")
        part = abilities["R"]["parts"][0]
        scaled = part.hp_scaled_damage
        assert scaled is not None
        min_dmg = _value("KogMaw", "R", "Minimum Magic Damage", 3)
        max_dmg = _value("KogMaw", "R", "Maximum Magic Damage", 3)
        assert min_dmg == pytest.approx(180.0)
        assert max_dmg == pytest.approx(360.0)
        assert scaled(0.0) == pytest.approx(min_dmg, abs=0.5)
        assert scaled(0.3) == pytest.approx(min_dmg * 1.25, abs=0.5)
        assert scaled(1.0) == pytest.approx(max_dmg, abs=0.5)

    def test_r_fight_lands_between_bounds(self) -> None:
        """The fight's R hit prices the missing-HP curve above the flat min.

        A **time-based** fight, deliberately: an hp-scaled part is priced
        against the state at its own landing instant, and in one rotation
        every cast lands at t=0.0, so R would read a full-health target and
        sit exactly on the minimum -- the curve would go untested.  Here R
        is cast at 0.25, after Q has landed, which is the fight this row is
        about.
        """
        combat = _fight("KogMaw", fight_mode="time_based", duration=6)
        events = _main_events(combat, "R")
        assert len(events) == 1
        raw = float(events[0]["raw_damage"])
        assert _value("KogMaw", "R", "Minimum Magic Damage", 3) < raw
        assert raw <= _value("KogMaw", "R", "Maximum Magic Damage", 3) + 0.01

    def test_r_stacks_are_mana_only_no_damage_option(self) -> None:
        """R stacks (cap 9, +40 mana each) change no damage — the module
        exposes no stack option and prices no stack damage."""
        _, abilities = _parse("KogMaw")
        assert "r_stacks" not in abilities
        assert abilities["R"]["parts"][0].amount == 0.0  # hp-scaled only


# ---------------------------------------------------------------------------
# Volibear — P Relentless Storm stacks + W Wounded 2nd bite
# ---------------------------------------------------------------------------


class TestVolibear:
    """P: 5 stacks of 5% (+3% per 100 AP) bonus AS + Lightning Claws;
    W: the Wounded bite deals 50% (+25% per 100 bonus AD) more."""

    def test_p_stat_buff_fully_stacked(self) -> None:
        stats, abilities = _parse("Volibear")
        assert abilities["passive"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            25.0
        )
        assert stats["attack_damage"] == 124.0  # sanity for W base below

    def test_p_stat_buff_partial_stacks(self) -> None:
        _, abilities = _parse("Volibear", options={"relentless_storm_stacks": 3})
        assert abilities["passive"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            15.0
        )

    def test_p_stat_buff_scales_with_ap(self) -> None:
        _, abilities = _parse("Volibear", ap=100.0)
        # 5 stacks x (5% + 3% per 100 AP) = 5 x 8% = 40%.
        assert abilities["passive"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            40.0
        )

    def test_p_lightning_claws_on_hit_only_at_five_stacks(self) -> None:
        _, abilities = _parse("Volibear", options={"relentless_storm_stacks": 4})
        assert "on_hit" not in abilities["passive"]
        _, abilities = _parse("Volibear")
        on_hit = abilities["passive"]["on_hit"]
        expected = _value("Volibear", "P", "Bonus Magic Damage", 18)
        assert expected == pytest.approx(60.0)
        assert on_hit["damage_per_hit"] == pytest.approx(expected)
        assert on_hit["damage_type"] == "magic"

    def test_w_wounded_bite_increases_damage(self) -> None:
        """Rank 5 vs no items: base 105 + 110% AD; the 2nd bite adds 50%."""
        stats, abilities = _parse("Volibear")
        base = (
            _value("Volibear", "W", "Physical Damage", 5) + 1.1 * stats["attack_damage"]
        )
        assert abilities["W"]["total_raw"] == pytest.approx(base * 1.5, abs=0.1)
        assert len(abilities["W"]["parts"]) == 2  # base + Wounded bonus

    def test_w_unmarked_first_cast_is_plain(self) -> None:
        _, abilities = _parse("Volibear", options={"w_wounded": False})
        base = 105.0 + 1.1 * _stats("Volibear")["attack_damage"]
        assert abilities["W"]["total_raw"] == pytest.approx(base, abs=0.1)
        assert len(abilities["W"]["parts"]) == 1

    def test_fight_w_prices_the_wounded_bite(self) -> None:
        """One bite, two parts, both on the cached 0.25s cast time."""
        combat = _fight("Volibear")
        events = _main_events(combat, "W")
        assert len(events) == 2
        ad = _stats("Volibear")["attack_damage"]
        assert sum(float(event["raw_damage"]) for event in events) == pytest.approx(
            (105.0 + 1.1 * ad) * 1.5, abs=0.2
        )
        assert {round(float(event["time"]), 3) for event in events} == {0.25}

    def test_fight_lightning_claws_ride_autos(self) -> None:
        combat = _fight(
            "Volibear", fight_mode="timed", duration=5, include_auto_attacks=True
        )
        sources = _main_sources(combat)
        assert "Lightning Claws (on-hit)" in sources
        assert sources["Lightning Claws (on-hit)"] > 0.0


# ---------------------------------------------------------------------------
# Senna — P Mist stacks + Weakened Soul mark
# ---------------------------------------------------------------------------


class TestSenna:
    """P: Mist grants 0.75 AD per stack and 10% crit per 20 stacks; the
    mark procs % current-health bonus physical damage every 2nd hit."""

    def test_mist_stat_buff_at_default_40(self) -> None:
        _, abilities = _parse("Senna")
        buff = abilities["passive"]["stat_buff"]
        assert buff["bonus_attack_damage"] == pytest.approx(0.75 * 40)
        assert buff["critical_strike_chance"] == pytest.approx(20.0)

    def test_mist_stat_buff_scales_per_20(self) -> None:
        _, abilities = _parse("Senna", options={"senna_mist_stacks": 60})
        buff = abilities["passive"]["stat_buff"]
        assert buff["bonus_attack_damage"] == pytest.approx(45.0)
        assert buff["critical_strike_chance"] == pytest.approx(30.0)

    def test_mist_buffs_q_scaling(self) -> None:
        """Q rank 5: 130 + 60% bonus AD; Mist's 30 AD rides the ratio."""
        _, abilities = _parse("Senna", bonus_ad_override=0.0)
        q = abilities["Q"]
        assert q["total_raw"] == pytest.approx(130.0 + 0.6 * (0.75 * 40), abs=0.5)

    def test_mark_on_hit_every_second_hit(self) -> None:
        on_hit = _parse("Senna")[1]["passive"]["on_hit"]
        assert on_hit["stacks_required"] == 2
        assert on_hit["count_ability_hits"] is True
        assert on_hit["damage_type"] == "physical"
        pct = _value("Senna", "P", "Current Health Damage", 18)
        assert pct == pytest.approx(10.0)
        # (10% of 2000) / 2 stacking hits = 100 per hit.
        assert on_hit["damage_per_hit"] == pytest.approx(100.0)

    def test_fight_prices_mist_and_mark(self) -> None:
        combat = _fight(
            "Senna", fight_mode="timed", duration=5, include_auto_attacks=True
        )
        sources = _main_sources(combat)
        assert "Weakened Soul (mark consume)" in sources
        assert sources["Weakened Soul (mark consume)"] > 0.0
        # Q benefits from the Mist AD buff: 130 + 0.6 x 30 bonus AD.
        q_events = _main_events(combat, "Q")
        assert len(q_events) == 1
        assert float(q_events[0]["raw_damage"]) == pytest.approx(
            130.0 + 0.6 * (0.75 * 40), abs=0.5
        )
        mark_events = _main_events(combat, "on_hit_ability_passive")
        auto_events = _main_events(combat, "auto_attacks")
        assert len(mark_events) >= len(auto_events) // 2


# ---------------------------------------------------------------------------
# Thresh — P Damnation souls
# ---------------------------------------------------------------------------


class TestThresh:
    """P: each Soul grants 1 AP and 1 bonus armor."""

    def test_soul_stat_buff_default_40(self) -> None:
        _, abilities = _parse("Thresh")
        buff = abilities["passive"]["stat_buff"]
        assert buff["ability_power"] == pytest.approx(40.0)
        assert buff["bonus_armor"] == pytest.approx(40.0)

    def test_soul_stat_buff_option(self) -> None:
        _, abilities = _parse("Thresh", options={"souls": 20})
        buff = abilities["passive"]["stat_buff"]
        assert buff["ability_power"] == pytest.approx(20.0)
        assert buff["bonus_armor"] == pytest.approx(20.0)

    def test_souls_buff_q_ap_ratio(self) -> None:
        """Q rank 5: 300 + 90% AP; 40 souls add 36."""
        _, abilities = _parse("Thresh")
        assert abilities["Q"]["total_raw"] == pytest.approx(300.0 + 0.9 * 40.0)

    def test_fight_q_prices_soul_ap(self) -> None:
        combat = _fight("Thresh")
        events = _main_events(combat, "Q")
        assert len(events) == 1
        assert float(events[0]["raw_damage"]) == pytest.approx(
            300.0 + 0.9 * 40.0, abs=0.5
        )


# ---------------------------------------------------------------------------
# Aurora — P Spirit Abjuration 3-hit %maxHP
# ---------------------------------------------------------------------------


class TestAurora:
    """P: every 3rd damaging hit (autos AND abilities) procs % max HP."""

    def test_passive_three_stack_proc(self) -> None:
        _, abilities = _parse("Aurora", ap=100.0)
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["stacks_required"] == 3
        assert on_hit["count_ability_hits"] is True
        # (1% + 2.7% per 100 AP) x 2000 = 74 per proc / 3 hits.
        assert on_hit["damage_per_hit"] == pytest.approx(74.0 / 3, abs=0.01)

    def test_fight_ability_hits_proc_passive_once(self) -> None:
        """Q (2 hits) + E (1) + R (1) = 4 ability hits -> 1 complete proc."""
        combat = _fight("Aurora")
        sources = _main_sources(combat)
        assert "Spirit Abjuration" in sources
        procs = _main_events(combat, "on_hit_ability_passive")
        assert len(procs) == 1


# ---------------------------------------------------------------------------
# Katarina — P dagger-retrieval spin (Sinister Steel)
# ---------------------------------------------------------------------------


class TestKatarina:
    """P: each dagger retrieval spins for level flat + 60% bonus AD +
    the level-banded AP ratio."""

    def test_spin_damage_at_level_18(self) -> None:
        _, abilities = _parse("Katarina", ap=100.0)
        flat = _value("Katarina", "P", "Bonus Magic Damage", 18)
        assert flat == pytest.approx(240.0)
        assert abilities["passive"]["total_raw"] == pytest.approx(flat + 100.0, abs=0.5)

    def test_spin_ap_ratio_bands(self) -> None:
        """Level 10 -> 80% AP; level 5 -> 70% AP (wiki bands)."""
        _, abilities = _parse("Katarina", ap=100.0, level=10)
        flat = _value("Katarina", "P", "Bonus Magic Damage", 10)
        assert abilities["passive"]["total_raw"] == pytest.approx(flat + 80.0, abs=0.5)
        _, abilities = _parse("Katarina", ap=100.0, level=5)
        flat = _value("Katarina", "P", "Bonus Magic Damage", 5)
        assert abilities["passive"]["total_raw"] == pytest.approx(flat + 70.0, abs=0.5)

    def test_spin_counts_bonus_ad(self) -> None:
        _, abilities = _parse("Katarina", bonus_ad_override=100.0)
        flat = _value("Katarina", "P", "Bonus Magic Damage", 18)
        # +60% bonus AD = 60.
        assert abilities["passive"]["total_raw"] == pytest.approx(flat + 60.0, abs=0.5)

    def test_fight_spin_procs_per_dagger_option(self) -> None:
        combat = _fight("Katarina", options={"p_daggers": 2})
        events = _main_events(combat, "passive")
        assert len(events) == 2
        flat = _value("Katarina", "P", "Bonus Magic Damage", 18)
        assert all(
            float(e["raw_damage"]) == pytest.approx(flat, abs=0.5) for e in events
        )


# ---------------------------------------------------------------------------
# Xayah — P Clean Cuts stacks feed E Bladecaller's feather detonation
# ---------------------------------------------------------------------------


class TestXayah:
    """P: casts generate 3 Clean Cuts stacks (cap 5); each empowered auto
    plants a Feather; E detonates per-Feather damage x feather count."""

    def test_clean_cuts_state_slot(self) -> None:
        _, abilities = _parse("Xayah")
        assert abilities["passive"]["total_raw"] == 0.0
        assert "5/5 stack(s)" in abilities["passive"]["detail"]

    def test_e_detonates_per_feather_damage(self) -> None:
        _, abilities = _parse("Xayah")
        per_feather = _value("Xayah", "E", "Physical Damage Per Feather", 5)
        assert per_feather == pytest.approx(110.0)
        assert abilities["E"]["total_raw"] == pytest.approx(per_feather * 7, abs=0.5)
        assert abilities["E"]["parts"][0].count == 7

    def test_e_feather_count_option(self) -> None:
        _, abilities = _parse("Xayah", options={"bladecaller_feathers": 12})
        per_feather = _value("Xayah", "E", "Physical Damage Per Feather", 5)
        assert abilities["E"]["total_raw"] == pytest.approx(per_feather * 12, abs=0.5)

    def test_e_emits_sourced_root_at_three_feathers(self) -> None:
        _, abilities = _parse("Xayah", options={"bladecaller_feathers": 3})
        control = abilities["E"]["control_events"][0]
        assert control.kind == "root"
        assert control.duration == pytest.approx(1.25)
        assert abilities["E"]["control_source_atoms"][0]["atom_id"] == (
            "timing.control_duration"
        )

    def test_e_without_three_feathers_has_no_root(self) -> None:
        _, abilities = _parse("Xayah", options={"bladecaller_feathers": 2})
        assert "control_events" not in abilities["E"]

    def test_fight_e_prices_feathers(self) -> None:
        combat = _fight("Xayah")
        events = _main_events(combat, "E")
        damage_events = [event for event in events if float(event["damage"]) > 0.0]
        assert len(damage_events) == 1  # the multi-Feather part aggregates at the cast
        per_feather = _value("Xayah", "E", "Physical Damage Per Feather", 5)
        assert float(damage_events[0]["raw_damage"]) == pytest.approx(
            per_feather * 7, abs=0.5
        )
        control = next(event for event in events if event.get("cc_kind") == "root")
        assert control["cc_duration"] == pytest.approx(1.25)


# ---------------------------------------------------------------------------
# Zac — no damage-relevant stack mechanic (boundary documented)
# ---------------------------------------------------------------------------


class TestZac:
    """The E3 worklist assigns Zac no damage-relevant stacks: Goo chunks
    heal and reduce W's cooldown; the passive stays a state row."""

    def test_no_stack_option_exposed(self) -> None:
        from src.calculator.champions import champion_options_meta_map

        options = champion_options_meta_map().get("Zac", {}).get("options", [])
        assert not any("stack" in o["key"] or "chunk" in o["key"] for o in options)

    def test_kit_still_parses_and_fights(self) -> None:
        _, abilities = _parse("Zac")
        assert "Q" in abilities and "W" in abilities
        combat = _fight("Zac")
        assert len(_main_events(combat, "Q")) >= 1
        assert len(_main_events(combat, "R")) == 4  # 1 + 3 reduced bounces


# ---------------------------------------------------------------------------
# Syndra — P Transcendent splinters
# ---------------------------------------------------------------------------


class TestSyndra:
    """P: 120 splinters -> +15% total AP; 60+ -> W bonus true damage;
    R prices per-sphere damage."""

    def test_transcendent_ap_multiplier_at_120(self) -> None:
        _, abilities = _parse("Syndra", ap=100.0)
        assert abilities["passive"]["stat_buff"]["ability_power"] == pytest.approx(15.0)

    def test_transcendent_inactive_below_120(self) -> None:
        _, abilities = _parse("Syndra", ap=100.0, options={"splinters": 119})
        assert "passive" not in abilities

    def test_w_true_damage_at_60_splinters(self) -> None:
        _, abilities = _parse("Syndra", ap=100.0)
        parts = abilities["W"]["parts"]
        assert len(parts) == 2
        assert parts[1].damage_type == "true"
        # magic = 190 + 65% of (100 x 1.15) = 264.75;
        # true = (12% + 2% per 100 AP) x magic with AP = 115.
        magic = 190.0 + 0.65 * 115.0
        true_bonus = (0.12 + 0.02 * 115.0 / 100.0) * magic
        assert parts[1].amount == pytest.approx(true_bonus, abs=0.1)

    def test_r_per_sphere_damage(self) -> None:
        _, abilities = _parse("Syndra", ap=100.0)
        # 160 + 20% of 115 = 183 per sphere x 3 spheres.
        per_sphere = 160.0 + 0.20 * 115.0
        assert abilities["R"]["total_raw"] == pytest.approx(per_sphere * 3, abs=0.5)

    def test_fight_r_prices_three_spheres(self) -> None:
        combat = _fight("Syndra")
        events = _main_events(combat, "R")
        assert len(events) == 1  # the per-sphere part aggregates at the cast
        assert float(events[0]["raw_damage"]) == pytest.approx(160.0 * 3, abs=0.5)


# ---------------------------------------------------------------------------
# Master Yi — P Double Strike every-3rd-auto second strike
# ---------------------------------------------------------------------------


class TestMasterYi:
    """P: 3 auto stacks -> the next auto strikes twice; the second strike
    deals 50% AD physical damage."""

    def test_double_strike_on_hit(self) -> None:
        stats, abilities = _parse("MasterYi")
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["stacks_required"] == 3
        assert on_hit["damage_type"] == "physical"
        # 50% of total AD spread across the 3 stacking hits.
        assert on_hit["damage_per_hit"] == pytest.approx(
            0.5 * stats["attack_damage"] / 3, abs=0.5
        )

    def test_double_strike_scales_with_ad(self) -> None:
        _, abilities = _parse("MasterYi", ad_override=200.0)
        assert abilities["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(
            0.5 * 200.0 / 3, abs=0.5
        )

    def test_fight_second_strike_tracks_autos(self) -> None:
        combat = _fight(
            "MasterYi", fight_mode="timed", duration=5, include_auto_attacks=True
        )
        sources = _main_sources(combat)
        assert "Double Strike (second strike)" in sources
        assert sources["Double Strike (second strike)"] > 0.0
        strikes = _main_events(combat, "on_hit_ability_passive")
        autos = _main_events(combat, "auto_attacks")
        assert len(strikes) == len(autos) >= 1


# ---------------------------------------------------------------------------
# Fiora — P Duelist's Dance vitals
# ---------------------------------------------------------------------------


class TestFiora:
    """P: each vital hit is level-scaled true damage (user-set count)."""

    def test_vital_per_proc_level_scaled(self) -> None:
        _, abilities = _parse("Fiora", options={"p_vitals": 1})
        vital = _value("Fiora", "P", "Bonus Damage", 18)
        assert vital == pytest.approx(100.0)
        assert abilities["passive"]["total_raw"] == pytest.approx(vital, abs=0.5)
        assert abilities["passive"]["parts"][0].damage_type == "true"

    def test_vital_count_option(self) -> None:
        _, abilities = _parse("Fiora", options={"p_vitals": 3})
        vital = _value("Fiora", "P", "Bonus Damage", 18)
        assert abilities["passive"]["total_raw"] == pytest.approx(vital * 3, abs=0.5)

    def test_fight_vital_procs_true_damage(self) -> None:
        combat = _fight("Fiora", options={"p_vitals": 1})
        events = _main_events(combat, "passive")
        assert len(events) == 1
        assert float(events[0]["raw_damage"]) == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# Jinx — Q Rev'd Up stacks + P Get Excited! takedown stacks
# ---------------------------------------------------------------------------


class TestJinx:
    """Q: 3 Pow-Pow stacks of bonus AS (first + subsequent per stack);
    P: 25% total attack speed per takedown stack, up to 5."""

    def test_rev_up_three_stacks(self) -> None:
        _, abilities = _parse("Jinx")
        q = abilities["Q"]
        first = _value("Jinx", "Q", "Bonus Attack Speed", 5)
        subsequent = _value("Jinx", "Q", "Attack Speed per Subsequent Stack", 5)
        assert first == pytest.approx(65.0)
        assert subsequent == pytest.approx(32.5)
        assert q["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            first + 2 * subsequent
        )

    def test_rev_up_zero_stacks(self) -> None:
        _, abilities = _parse("Jinx", options={"jinx_rev_up_stacks": 0})
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(0.0)

    def test_get_excited_five_stacks(self) -> None:
        _, abilities = _parse("Jinx", options={"jinx_get_excited_stacks": 5})
        assert abilities["passive"]["stat_buff"]["total_attack_speed_percent"] == (
            pytest.approx(125.0)
        )

    def test_fight_get_excited_raises_autos(self) -> None:
        base = _fight("Jinx", fight_mode="timed", duration=5, include_auto_attacks=True)
        excited = _fight(
            "Jinx",
            fight_mode="timed",
            duration=5,
            include_auto_attacks=True,
            options={"jinx_get_excited_stacks": 5},
        )
        base_autos = len(_main_events(base, "auto_attacks"))
        excited_autos = len(_main_events(excited, "auto_attacks"))
        assert excited_autos > base_autos
