"""P4 — Senna "Relic Cannon" 20% AD on-hit rider (test-matrix owner: RLM-2 C).

Focused TDD matrix for Relic Cannon's basic-attack on-hit rider.  CURRENT
RUNTIME FACTS (verify-before-pin completed, all pinned in S1):

- The module (``src/calculator/champions/senna.py``) ships ``_absolution``:
  the BUFF-phase P packet with the Mist ``stat_buff`` and ONE ``on_hit``
  dict (Weakened Soul mark: ``name``, ``damage_per_hit``, ``damage_type``,
  ``stacks_required`` 2, ``count_ability_hits`` True) — the engine's
  on-hit contract is ONE per-auto payload per ability entry
  (``damage._layer_on_hit_effects`` reads ``ability_info.get("on_hit")``).
- The cached P effects[3] prose (the ONLY Relic Cannon evidence):
  "Innate - Relic Cannon: Senna's basic attacks on-hit deal 20% AD bonus
  physical damage and grant her 10% / 15% / 20% (based on level) of the
  target's movement speed as bonus movement speed for 0.5 seconds. The
  damage applies life steal at 100% effectiveness." — ``leveling`` EMPTY.
- The P notes carry the boundaries: the rider applies only when the
  attack deals > 0 damage, is NOT applied against structures, and adds a
  Black Cleaver stack.
- Atoms: the ONLY P leveling atom is ``ability.current _health _damage``
  (hash ``154193655afce7e0``); there is NO Relic Cannon atom.  Binary:
  ``data/bin/characters/senna.bin.json`` SennaPassive carries
  ``MSStealDuration: 0.5`` (the MS-steal duration corroboration) but NO
  on-hit AD ratio DataValue — the 20% is script-side, no binary number.
- Module ASSUMPTION (verbatim): "Relic Cannon's on-hit 20% AD bonus
  physical damage is not modeled (the packet has no leveling row for it)".
- Default surface today: no rider row anywhere; the registered golden
  Senna fights (4 builds x levels 11/18, burst + sustained) match the
  current pipeline byte-for-byte (2-dp) with NO rider contribution.

CONTRACT PINNED HERE (the P4 completion must satisfy; genuinely-unsupported
behavior is a STRICT xfail with reason "awaiting P4-Senna-Relic ..." — the
coordinator flips each xfail to a live test when the seam lands):

- S1  Source evidence: the four P effect descriptions + the notes'
      relevant lines, the empty leveling status, the 20% AD + 10/15/20%
      + 0.5s numbers, the atoms (Current Health Damage atom id/hash,
      Relic Cannon atom absence), the module declaration, the binary
      evidence (MSStealDuration present, ratio absent).
- S2  Default + absent parity: today's default surface is rider-free and
      the golden file matches the current pipeline.  The coordinator's
      decision OPT-IN vs INHERENT is left open: an opt-in option must
      make absent == False byte-identical; an inherent rider must have
      every registered-fight golden delta explained by the formula
      N_autos x 0.20 x bonus AD x mitigation.
- S3  Rider on the right auto path: 20% of bonus AD on EVERY basic
      attack (not every-2nd — the mark cadence is separate); the damage
      is 0.20 x bonus AD (per the brief; see AMBIGUITY note in the
      header footer); its own breakdown row/payload, count == autos.
- S4  Marks and ability hits: the Weakened Soul 2-hit cadence and the
      ability-hit counting are untouched; the rider does NOT fire on
      ability hits nor on Q's item-on-hit applications.
- S5  Target/structure boundaries: the notes' structure + >0-damage
      rules are pinned verbatim; the engine has no structure-target
      concept, so the modeled rider must name the boundary fail-closed.
- S6  Multiple autos: N autos -> N rider procs.
- S7  One rotation: the rider rides the one-rotation auto stream when a
      stream is present; zero autos -> zero rider.
- S8  Zero autos: no rider damage, fight total unchanged.
- S9  API validation: today unknown rider option keys are 400s; the
      declared option (any spelling) must be a typed control in the meta
      with junk rejected.
- S10 Score/receipt parity: full vs score_only byte-identical today and
      the rider row must be byte-identical once modeled.
- S11 Unchanged boundaries: Mist ledger, Weakened Soul pricing, Q/W/R
      damage, item on-hits (Kraken counter), and the OTHER engine on-hit
      consumers (Vayne W, Corki P true rider) untouched.
- S12 Regression surface: the mandated sanity list (footer).

AMBIGUITY NOTE for the coordinator (value source): the brief pins the
rider damage as 0.20 x BONUS AD.  The wiki prose says "20% AD" — the
template convention where an unqualified "AD" means TOTAL AD (contrast
the same packet's "60% bonus AD" for Q) — and the binary carries no
value.  S3 pins the brief's bonus-AD reading; switching to total AD is a
one-line change in the S3 formula pins (flag in the completion notes).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, ONE_ROTATION_DURATION, run_fight
from src.calculator.stats import calculate_total_stats
from src.calculator.champions.slotlib import find_named_leveling
from tests.parse_stats import parse_stats

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_ABILITIES_ATOMS = json.loads(
    Path("data/atoms/abilities.json").read_text(encoding="utf-8")
)["objects"]
_SENNA_BIN_PATH = Path("data/bin/characters/senna.bin.json")
_SENNA_BIN = (
    json.loads(_SENNA_BIN_PATH.read_text(encoding="utf-8"))
    if _SENNA_BIN_PATH.exists()
    else None
)
_ITEMS = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
_GOLDEN = json.loads(Path("scripts/golden_baseline.json").read_text(encoding="utf-8"))
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_AWAIT = "awaiting P4-Senna-Relic ..."
# Rider breakdown-row spellings the seam may land (contract: ONE of them,
# count == autos, distinct from on_hit_ability_passive).
_RIDER_ROW_KEYS = (
    "on_hit_ability_P2",
    "on_hit_ability_passive_relic_cannon",
    "on_hit_ability_passive_2",
    "relic_cannon_on_hit",
    "on_hit_relic_cannon",
    "on_hit_ability_relic_cannon",
)


def _parse(option: dict | None):
    stats = parse_stats(_LEVEL)
    return stats, parse_champion_abilities(
        get_champion("Senna"),
        _LEVEL,
        0.0,
        ability_ranks=_RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": 2000.0},
        champion_options=option,
    )


def _fight(
    option: dict,
    *,
    duration: float = 10.0,
    score_only: bool = False,
    cast_order: list[str] | None = None,
    one_rotation: bool = False,
    items: list[dict] | None = None,
    auto_attack_uptime: float = 0.0,
    target_health: float = 2000.0,
) -> dict:
    stats, abilities = _parse(option)
    return calculate_fight_damage(
        stats,
        abilities,
        items or [],
        FightConfig(
            target_health=target_health,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=duration,
            auto_attack_uptime=auto_attack_uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=(cast_order if cast_order is not None else ["Q", "W", "R"]),
        ),
        score_only=score_only,
        champion_options=dict(option) if option else {},
    )


def _api(option: dict):
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Senna",
            "level": _LEVEL,
            "items": [],
            "role": "support",
            "ability_ranks": _RANKS,
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "target_health": 2000,
            "target_armor": 50,
            "target_mr": 40,
            "champion_options": option,
        },
    )


def _api_with_autos(option: dict):
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Senna",
            "level": _LEVEL,
            "items": [],
            "role": "support",
            "ability_ranks": _RANKS,
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "target_health": 2000,
            "target_armor": 50,
            "target_mr": 40,
            "champion_options": option,
        },
    )


def _p_effects() -> list[dict]:
    return _CHAMPION_DATA["Senna"]["abilities"]["P"][0]["effects"]


def _p_notes() -> str:
    return _CHAMPION_DATA["Senna"]["abilities"]["P"][0].get("notes", "")


def _relic_effect() -> dict:
    return _p_effects()[3]


def _item(name: str) -> dict:
    # data/items.json is a dict of named item records.
    for entry in _ITEMS.values():
        if entry.get("name") == name:
            return entry
    raise AssertionError(f"cached item {name!r} not found")


def _rider_row(result: dict) -> dict | None:
    """The rider breakdown row wherever the seam lands it (or None)."""
    breakdown = result.get("breakdown", {})
    for key in _RIDER_ROW_KEYS:
        row = breakdown.get(key)
        if isinstance(row, dict):
            return row
    return None


def _leveling(slot: str, attribute: str) -> dict:
    ability = _CHAMPION_DATA["Senna"]["abilities"][slot][0]
    leveling = find_named_leveling(ability, attribute)
    if leveling is None:
        raise AssertionError(f"Senna {slot} has no leveling {attribute!r}")
    return leveling


def _resolve(slot: str, attribute: str, index: int, stats: dict) -> float:
    total = 0.0
    for modifier in _leveling(slot, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(index, len(values) - 1)
        value = float(values[idx])
        unit = str(units[idx]).strip() if idx < len(units) else ""
        if unit in ("", "seconds"):
            total += value
        elif unit == "% bonus AD":
            total += value / 100.0 * stats["bonus_attack_damage"]
        elif unit == "% AP":
            total += value / 100.0 * stats.get("ability_power", 0.0)
        elif unit == "%":
            total += value
        else:
            raise AssertionError(f"unhandled unit {unit!r} in {slot} {attribute}")
    return total


def _mitigate(raw: float, armor: float) -> float:
    return raw * 100.0 / (100.0 + armor)


# ---------------------------------------------------------------------------
# S1 — Source evidence
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_p_all_four_effects_pinned_verbatim(self):
        effects = _p_effects()
        assert len(effects) == 4
        assert "Weakened Soul" in effects[0]["description"]
        assert "1% : 10% (based on level) of the target's current health" in (
            effects[0]["description"]
        )
        assert "Mist Wraith" in effects[1]["description"]
        assert "0.75 bonus attack damage" in effects[2]["description"]
        assert "20 bonus attack range" in effects[2]["description"]
        assert "10% critical strike chance" in effects[2]["description"]
        assert "Relic Cannon" in effects[3]["description"]

    def test_relic_cannon_prose_verbatim_and_leveling_empty(self):
        # The ONLY Relic Cannon evidence: the prose.  leveling is EMPTY —
        # the packet has no row for the on-hit 20% AD (module assumption).
        relic = _relic_effect()
        assert relic["description"] == (
            "Innate - Relic Cannon: Senna's basic attacks on-hit deal 20% "
            "AD bonus physical damage and grant her 10% / 15% / 20% (based "
            "on level) of the target's movement speed as bonus movement "
            "speed for 0.5 seconds. The damage applies life steal at 100% "
            "effectiveness."
        )
        assert relic["leveling"] == []

    def test_p_leveling_rows_are_only_the_mark(self):
        # The whole P packet's only leveling is the mark's Current Health
        # Damage — nothing for Mist, the wraith spawn, or Relic Cannon.
        for effect in _p_effects():
            for leveling in effect.get("leveling", []):
                assert leveling["attribute"] == "Current Health Damage"
        assert len(_p_effects()[0]["leveling"]) == 1

    def test_notes_relevant_lines_pinned(self):
        notes = _p_notes()
        assert (
            "Relic Cannon is only applied if the attack deals more than 0 damage."
            in notes
        )
        assert "not applied if the target is  invulnerable" in notes
        assert "The bonus damage is also not applied against  structures" in notes
        assert (
            "The bonus on-hit damage applies an additional stack of  Black Cleaver's Carve."
            in notes
        )
        assert "Attacking structures is special-cased to not grant it at all" in notes
        assert "Dealing 0 damage is valid for marking and collecting Mist" in notes

    def test_current_health_damage_atom_pinned(self):
        # The only P leveling atom: id + hash + source row.
        senna_atoms = _ABILITIES_ATOMS["Senna"]
        atom = next(
            a
            for a in senna_atoms
            if a["atom_id"] == "ability.current _health _damage"
            and a["source"] == "Senna.P[0].effects[0].leveling[0].modifiers[0]"
        )
        assert atom["hash"] == "154193655afce7e0"
        assert atom["values"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert atom["units"] == ["%"] * 10
        assert atom["evidence"] == ["Current Health Damage@effects[0]"]

    def test_no_relic_cannon_atom_anywhere(self):
        # The 20% AD has NO atom (no leveling row -> nothing to atomize).
        # It must enter through the module-constant-with-receipt pattern
        # (the Mist constants precedent) — never a silent literal.
        senna_atoms = _ABILITIES_ATOMS["Senna"]
        assert not any(
            "Relic" in json.dumps(a) or "Cannon" in json.dumps(a) for a in senna_atoms
        )
        assert not any(
            a["source"].startswith("Senna.P[0].effects[3]") for a in senna_atoms
        )

    def test_binary_evidence_ms_steal_present_ratio_absent(self):
        # Binary corroboration: MSStealDuration 0.5 (the prose's 0.5s) is
        # a SennaPassive DataValue; the 20% on-hit AD ratio is a
        # GameCalculation (mSpellCalculations.BonusOnHitDamage =
        # StatByCoefficient mStat 2, no mStatFormula, coefficient 0.2) —
        # NOT a DataValue, which is why a DataValue-only scan misses it.
        if _SENNA_BIN is None:
            pytest.skip("local Senna game-file evidence is unavailable")
        passive = _SENNA_BIN["Characters/Senna/Spells/SennaPassiveAbility/SennaPassive"]
        values = {dv["name"]: dv["values"] for dv in passive["mSpell"]["DataValues"]}
        assert values["MSStealDuration"] == [0.5] * 7
        assert not any(
            "OnHit" in name or "ADRatio" in name or "OnHitPercent" in name
            for name in values
        )
        calcs = passive["mSpell"].get("mSpellCalculations", {})
        bonus = calcs.get("BonusOnHitDamage", {})
        parts = bonus.get("mFormulaParts", [])
        assert parts and parts[0].get("mCoefficient") == pytest.approx(0.2)
        assert parts[0].get("mStat") == 2
        assert "mStatFormula" not in bonus  # total AD, not bonus AD

    def test_module_declaration_names_the_gap(self):
        meta = get_champion_options_meta("Senna")
        assert any(
            "MODELED as 20% of TOTAL AD" in text and "SENNA_RELIC_CANNON_RULE" in text
            for text in meta["assumptions"]
        )
        assert not any(
            "Relic Cannon's on-hit 20% AD bonus physical damage is not "
            "modeled" in text
            for text in meta["assumptions"]
        )
        sources = {row["label"]: row for row in meta["sources"]}
        assert sources["Senna P ability entry"]["revision_id"] == 2864157
        # Only the mist option is declared today (S9's API surface).
        assert [o["key"] for o in meta["options"]] == ["senna_mist_stacks"]

    def test_parse_snapshot_has_exactly_one_on_hit_payload(self):
        # The engine contract is one per-auto on_hit payload per entry —
        # the mark rides the P (passive) entry; the rider rides its OWN
        # P2 entry with its own payload (the smallest safe extension).
        _, abilities = _parse({"senna_mist_stacks": 40})
        passive = abilities["passive"]
        assert set(passive) == {
            "name",
            "rank",
            "damage_type",
            "total_raw",
            "parts",
            "stat_buff",
            "on_hit",
            "detail",
        }
        assert set(passive["on_hit"]) == {
            "name",
            "damage_per_hit",
            "damage_type",
            "stacks_required",
            "count_ability_hits",
        }
        assert passive["on_hit"]["name"] == "Weakened Soul (mark consume)"
        assert "P2" in abilities
        assert set(abilities["P2"]["on_hit"]) == {
            "name",
            "damage_per_hit",
            "damage_type",
        }

    def test_default_surface_is_rider_free_today(self):
        # The rider is INHERENT (source-backed — no option): every
        # auto-bearing fight carries on_hit_ability_P2.  Absent vs empty
        # options are byte-identical; only the P3 souls ledger row
        # differentiates the seeded surface.
        absent = _fight(None, duration=10.0, auto_attack_uptime=1.0, one_rotation=True)
        empty = _fight({}, duration=10.0, auto_attack_uptime=1.0, one_rotation=True)
        for result in (absent, empty):
            row = _rider_row(result)
            assert row is not None
            assert row["count"] == 8
            assert result["breakdown"]["auto_attacks"]["count"] == 8
            assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == (
                pytest.approx(104.0)
            )
        assert absent["breakdown"] == empty["breakdown"]
        seeded = _fight(
            {"senna_mist_stacks": 40},
            duration=10.0,
            auto_attack_uptime=1.0,
            one_rotation=True,
        )
        assert set(seeded["breakdown"]) - set(absent["breakdown"]) == {"mist"}
        assert seeded["breakdown"]["mist"]["starting_stacks"] == 40
        # The default already seeds 40 Mist stacks, so absent vs seeded
        # carry the SAME rider per-hit; a ZERO-stack config (AD 100) vs
        # the 40-stack config (AD 130) proves the rider reads the
        # Mist-buffed parse-time total AD.
        zero = _fight(
            {"senna_mist_stacks": 0},
            duration=10.0,
            auto_attack_uptime=1.0,
            one_rotation=True,
        )
        rider_zero = _rider_row(zero)
        rider_seeded = _rider_row(seeded)
        assert rider_zero["damage_per_hit"] == pytest.approx(
            0.2 * 100.0 * 100.0 / 150.0
        )
        assert rider_seeded["damage_per_hit"] == pytest.approx(
            rider_zero["damage_per_hit"] * 1.3
        )

    def test_registered_golden_senna_fights_match_current_pipeline(self):
        # The registered Senna fights in scripts/golden_baseline.json are
        # exactly what the current pipeline produces (2-dp rounding,
        # same FightParams as golden_snapshot). The reviewed baseline
        # includes the inherent rider in sustained fights.
        builds = {
            "no_items": [],
            "physical_build": [
                _item(n)
                for n in ("Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards")
            ],
            "magic_build": [
                _item(n) for n in ("Luden's Echo", "Shadowflame", "Rabadon's Deathcap")
            ],
            "spellblade_build": [
                _item(n)
                for n in ("Trinity Force", "Infinity Edge", "Berserker's Greaves")
            ],
        }
        registered = _GOLDEN["registered_champion_fights"]["Senna"]
        for level in (11, 18):
            for build_name, build_items in builds.items():
                for scenario, uptime, one_rotation in (
                    (build_name, 0.0, True),
                    ("sustained", 1.0, False),
                ):
                    want = (
                        registered[str(level)][build_name]
                        if scenario == build_name
                        else registered[str(level)]["sustained"][build_name]
                    )
                    data = json.loads(json.dumps(_CHAMPION_DATA["Senna"]))
                    stats = calculate_total_stats(data, level, build_items)
                    result = run_fight(
                        data,
                        level,
                        build_items,
                        FightParams(
                            target_health=2000.0,
                            target_bonus_health=0.0,
                            target_armor=50.0,
                            target_magic_resistance=40.0,
                            fight_duration_seconds=ONE_ROTATION_DURATION,
                            auto_attack_uptime=uptime,
                            one_rotation=one_rotation,
                            include_actives=True,
                            cast_order=None,
                            auto_attacks_only=False,
                            ability_ranks=None,
                            champion_options=None,
                            deterministic=True,
                        ),
                    )
                    totals = {
                        key: round(float(row.get("total_damage", 0.0)), 2)
                        for key, row in result["breakdown"].items()
                        if isinstance(row, dict)
                    }
                    got = {
                        "breakdown_totals": totals,
                        "total_damage": round(float(result["total_damage"]), 2),
                    }
                    rider = round(float(totals.get("on_hit_ability_P2", 0.0)), 2)
                    assert got == want, (
                        f"Senna {level} {scenario}/{build_name} golden drift "
                        f"(re-capture baseline and explain every delta)"
                    )
                    if scenario == build_name:
                        # Burst fights have no autos, so the rider row is absent.
                        assert rider == 0.0
                    else:
                        # Sustained fights include the reviewed inherent rider
                        # in both the current result and the golden baseline.
                        assert "on_hit_ability_P2" in totals
                        assert totals["on_hit_ability_P2"] > 0.0

    def test_golden_parse_snapshot_has_no_rider_payload(self):
        # The golden abilities_level_11 parse surface: the passive entry
        # keeps the single mark on_hit payload, and the snapshot now also
        # carries the P2 entry with the rider payload (the inherent
        # parse delta — explained in HANDOVER §4.64).
        snapshot = _GOLDEN["champion_baselines"]["Senna"]["abilities_level_11"][
            "passive"
        ]
        assert set(snapshot["on_hit"]) == {
            "name",
            "damage_per_hit",
            "damage_type",
            "stacks_required",
            "count_ability_hits",
        }
        assert snapshot["on_hit"]["name"] == "Weakened Soul (mark consume)"
        # The live parse includes the P2 rider entry; the checked-in
        # baseline does not (pre-rider) — the compare gate enumerates it.
        _, abilities = _parse({"senna_mist_stacks": 40})
        assert "P2" in abilities
        assert abilities["P2"]["on_hit"]["name"] == "Relic Cannon (on-hit)"

    def test_opt_in_absent_vs_false_byte_identical(self):
        # The rider is INHERENT (source-backed — no option): the option
        # surface stays exactly [senna_mist_stacks] and every relic
        # spelling is rejected at the API boundary (the fail-closed gate).
        meta = get_champion_options_meta("Senna")
        assert [o["key"] for o in meta["options"]] == ["senna_mist_stacks"]
        assert not any("relic" in o["key"] for o in meta["options"])
        absent = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        empty = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        assert absent["total_damage"] == empty["total_damage"]
        assert _rider_row(absent) is not None  # inherent: present by default

    def test_inherent_rider_golden_deltas_explained(self):
        # IF the rider is INHERENT (no option), every registered sustained
        # Senna fight must gain exactly N_autos x 0.20 x bonus AD
        # (mitigated physical) — the delta formula below.  Today no rider
        # exists, so the formula cannot be satisfied.
        builds = {
            "no_items": [],
            "physical_build": [
                _item(n)
                for n in ("Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards")
            ],
            "magic_build": [
                _item(n) for n in ("Luden's Echo", "Shadowflame", "Rabadon's Deathcap")
            ],
            "spellblade_build": [
                _item(n)
                for n in ("Trinity Force", "Infinity Edge", "Berserker's Greaves")
            ],
        }
        for level in (11, 18):
            for build_name, build_items in builds.items():
                data = json.loads(json.dumps(_CHAMPION_DATA["Senna"]))
                stats = calculate_total_stats(data, level, build_items)
                result = run_fight(
                    data,
                    level,
                    build_items,
                    FightParams(
                        target_health=2000.0,
                        target_bonus_health=0.0,
                        target_armor=50.0,
                        target_magic_resistance=40.0,
                        fight_duration_seconds=ONE_ROTATION_DURATION,
                        auto_attack_uptime=1.0,
                        one_rotation=False,
                        include_actives=True,
                        cast_order=None,
                        auto_attacks_only=False,
                        ability_ranks=None,
                        champion_options=None,
                        deterministic=True,
                    ),
                )
                autos = result["breakdown"]["auto_attacks"]["count"]
                # Parse-time Mist buff rides the fight stats (BUFF phase);
                # the rider's per-hit IS the P2 payload (0.2 x parse-time
                # total AD — the Mist-buffed, item-bearing attack damage).
                abilities = parse_champion_abilities(
                    data,
                    level,
                    stats["ability_power"],
                    ability_ranks=None,
                    champion_stats=stats,
                    target_stats={
                        "target_max_health": 2000.0,
                        "target_current_health": 2000.0,
                        "target_missing_health": 0.0,
                    },
                    champion_options=None,
                )
                raw_per_hit = abilities["P2"]["on_hit"]["damage_per_hit"]
                armor = float(result["effective_armor"])
                per_hit = _mitigate(raw_per_hit, armor)
                row = _rider_row(result)
                assert row is not None, f"{level}/{build_name}: rider row missing"
                assert row["count"] == autos
                assert row["total_damage"] == pytest.approx(per_hit * autos)


# ---------------------------------------------------------------------------
# S3 — The rider on the right auto path
# ---------------------------------------------------------------------------


class TestRiderAutoPath:
    def test_rider_procs_every_auto_not_every_2nd(self):
        # 8 autos + Q/W/R (11 shared mark hits): the rider count is the
        # AUTO count (8), never the mark's every-2nd count (5) — the mark
        # cadence is a separate counter.
        result = _fight(
            {"senna_mist_stacks": 40}, duration=10.0, auto_attack_uptime=1.0
        )
        row = _rider_row(result)
        assert row is not None
        assert row["count"] == result["breakdown"]["auto_attacks"]["count"] == 8
        assert result["breakdown"]["on_hit_ability_passive"]["count"] == 5

    def test_rider_damage_formula(self):
        # 0.20 x TOTAL AD (the binary BonusOnHitDamage: mStat 2, no
        # mStatFormula = total; the wiki prose "20% AD" unqualified) —
        # Mist-buffed 130 = 60 base + 40 bonus + 30 Mist, physical,
        # mitigated at the fight's effective armor.
        result = _fight(
            {"senna_mist_stacks": 40}, duration=10.0, auto_attack_uptime=1.0
        )
        row = _rider_row(result)
        assert row is not None
        armor = float(result["effective_armor"])
        assert row["damage_type"] == "physical"
        assert row["damage_per_hit"] == pytest.approx(_mitigate(0.20 * 130.0, armor))
        assert row["total_damage"] == pytest.approx(_mitigate(0.20 * 130.0, armor) * 8)

    def test_rider_payload_placement(self):
        # The rider rides its OWN BUFF-phase slot (P2) with its own on_hit
        # payload — the engine prices any entry's payload, so the P
        # (passive) entry keeps exactly the mark and no shared engine
        # change is needed (the one-payload-per-entry contract stands).
        _, abilities = _parse({"senna_mist_stacks": 40})
        assert "P2" in abilities
        assert abilities["P2"]["on_hit"]["name"] == "Relic Cannon (on-hit)"
        assert abilities["P2"]["on_hit"]["damage_per_hit"] == pytest.approx(0.2 * 130.0)
        passive = abilities["passive"]
        assert "on_hit_extra" not in passive and "on_hits" not in passive
        assert passive["on_hit"]["name"] == "Weakened Soul (mark consume)"
        result = _fight(
            {"senna_mist_stacks": 40}, duration=10.0, auto_attack_uptime=1.0
        )
        row = _rider_row(result)
        assert row is not None

    def test_weakened_soul_cadence_unaffected(self):
        # The mark: 8 autos + Q/W/R = 11 shared hits -> 5 procs at the
        # per-hit share (10% of max health / 2), mitigated physical.
        result = _fight(
            {"senna_mist_stacks": 40}, duration=10.0, auto_attack_uptime=1.0
        )
        mark = result["breakdown"]["on_hit_ability_passive"]
        assert mark["name"] == "Weakened Soul (mark consume)"
        assert mark["count"] == 5
        assert mark["damage_per_hit"] == pytest.approx(
            _mitigate(0.10 * 2000.0, float(result["effective_armor"]))
        )
        _, abilities = _parse({"senna_mist_stacks": 40})
        assert abilities["passive"]["on_hit"]["stacks_required"] == 2
        assert abilities["passive"]["on_hit"]["count_ability_hits"] is True

    def test_rider_does_not_fire_on_ability_hits(self):
        # Q/W/R hit (count_ability_hits mark procs fire: 3 hits -> 1
        # proc) but with zero autos the rider must be absent; with autos,
        # the rider count equals the AUTO count even though the mark
        # counts 3 extra ability hits.
        no_autos = _fight({"senna_mist_stacks": 40}, one_rotation=True)
        assert no_autos["breakdown"]["on_hit_ability_passive"]["count"] == 1
        assert _rider_row(no_autos) is None
        with_autos = _fight(
            {"senna_mist_stacks": 40}, duration=10.0, auto_attack_uptime=1.0
        )
        row = _rider_row(with_autos)
        assert row is not None
        assert row["count"] == 8  # never 8 + 3 ability hits

    def test_rider_does_not_ride_q_item_applications(self):
        # Q applies item on-hits (applies_item_on_hits: 1 hit per cast),
        # feeding the shared Kraken counter — the rider is a basic-attack
        # on-hit and must NOT add applications on Q casts.
        result = _fight(
            {"senna_mist_stacks": 40},
            duration=10.0,
            auto_attack_uptime=1.0,
            items=[_item("Kraken Slayer")],
        )
        row = _rider_row(result)
        assert row is not None
        assert row["count"] == result["breakdown"]["auto_attacks"]["count"]
        # The Kraken counter counts on-hit APPLICATIONS (8 autos + 1 Q
        # cast via applies_item_on_hits, every 3rd hit): the rider is a
        # separate payload row and adds no applications.
        assert result["breakdown"]["on_hit_Kraken Slayer"]["count"] == 3


# ---------------------------------------------------------------------------
# S5 — Target and structure boundaries
# ---------------------------------------------------------------------------


class TestTargetAndStructureBoundaries:
    def test_structure_and_zero_damage_rules_pinned_from_notes(self):
        # The named boundaries live in the cached notes today; the engine
        # has no structure-target concept (S5 xfail pins the fail-closed
        # contract for the modeled rider).
        notes = _p_notes()
        assert "not applied against  structures" in notes
        assert "only applied if the attack deals more than 0 damage" in notes
        assert "invulnerable" in notes

    def test_rider_structure_boundary_fail_closed(self):
        # Once modeled, the rider must name the structure/zero-damage
        # boundary fail-closed (the notes' rules) — an assumption line or
        # an explicit no-structure-target flag, never silent application.
        meta = get_champion_options_meta("Senna")
        assert any(
            "structure" in text.lower() or "0 damage" in text.lower()
            for text in meta["assumptions"]
        ), "no named structure/zero-damage boundary for the rider"


# ---------------------------------------------------------------------------
# S6 — Multiple autos
# ---------------------------------------------------------------------------


class TestMultipleAutos:
    def test_n_autos_n_rider_procs(self):
        for duration, want_autos in ((5.0, 4), (10.0, 8)):
            result = _fight(
                {"senna_mist_stacks": 40},
                duration=duration,
                auto_attack_uptime=1.0,
            )
            assert result["breakdown"]["auto_attacks"]["count"] == want_autos
            row = _rider_row(result)
            assert row is not None
            assert row["count"] == want_autos
            assert row["total_damage"] == pytest.approx(
                row["damage_per_hit"] * want_autos
            )


# ---------------------------------------------------------------------------
# S7 — One rotation
# ---------------------------------------------------------------------------


class TestOneRotation:
    def test_rider_in_one_rotation_with_stream(self):
        # one_rotation keeps the auto stream (uptime 1.0 -> 8 autos): the
        # rider rides it; the mark still shares the Q/W/R hits.
        result = _fight(
            {"senna_mist_stacks": 40},
            duration=10.0,
            auto_attack_uptime=1.0,
            one_rotation=True,
        )
        row = _rider_row(result)
        assert row is not None
        assert row["count"] == 8
        assert result["breakdown"]["on_hit_ability_passive"]["count"] == 5

    def test_one_rotation_without_stream_has_no_rider(self):
        result = _fight({"senna_mist_stacks": 40}, one_rotation=True)
        assert _rider_row(result) is None
        assert result["breakdown"]["auto_attacks"]["count"] == 0
        assert result["breakdown"]["on_hit_ability_passive"]["count"] == 1


# ---------------------------------------------------------------------------
# S8 — Zero autos
# ---------------------------------------------------------------------------


class TestZeroAutos:
    def test_no_autos_no_rider_damage(self):
        # Zero autos: the rider contributes nothing; the fight total is
        # the pinned Q/W/R + mark value (863.666... at level 18, 40 Mist).
        result = _fight({"senna_mist_stacks": 40}, one_rotation=True)
        assert _rider_row(result) is None
        assert result["total_damage"] == pytest.approx(863.6666666666665)
        # Same for a timed fight with no auto stream.
        result = _fight({"senna_mist_stacks": 40}, duration=10.0)
        assert _rider_row(result) is None


# ---------------------------------------------------------------------------
# S9 — API validation surface
# ---------------------------------------------------------------------------


class TestApiValidation:
    def test_unknown_rider_option_keys_rejected_today(self):
        # No rider option is declared: any spelling fails closed with the
        # named 400 receipt (never silently accepted).
        for key in (
            "senna_relic_cannon",
            "relic_cannon",
            "senna_rider",
            "relic_cannon_model",
        ):
            response = _api({key: True})
            assert response.status_code == 400
            assert response.get_json()["error"] == (
                f"champion_options contains unknown option {key}"
            )
        response = _api({"senna_mist_stacks": 40})
        assert response.status_code == 200

    def test_declared_rider_option_validates_typed(self):
        # The rider is INHERENT — no option is declared, so every relic
        # spelling is rejected at the API boundary with the named 400
        # (the fail-closed gate), and the rider flows without any input.
        meta = get_champion_options_meta("Senna")
        assert [o["key"] for o in meta["options"]] == ["senna_mist_stacks"]
        for spelling in ("relic_cannon", "relic_cannon_on_hit", "relic_rider"):
            resp = _api({spelling: True})
            assert resp.status_code == 400
            assert "unknown option" in resp.get_json()["error"].lower()
        ok = _api({})
        assert ok.status_code == 200
        body = ok.get_json()["breakdown"]
        # The API default fight has no auto stream (include_auto_attacks
        # False), so the rider row is absent — the zero-auto boundary.
        assert "on_hit_ability_P2" not in body
        with_autos = _api_with_autos({})
        assert with_autos.status_code == 200
        assert "on_hit_ability_P2" in with_autos.get_json()["breakdown"]

    def test_score_parity_with_autos_today(self):
        # No-takedown fight (target survives): full and score_only agree
        # byte-for-byte across the breakdown, totals, and resource ledger
        # — the surface the rider row must join without divergence.
        full = _fight(
            {"senna_mist_stacks": 40},
            duration=10.0,
            auto_attack_uptime=1.0,
            one_rotation=True,
            target_health=5000.0,
        )
        scored = _fight(
            {"senna_mist_stacks": 40},
            duration=10.0,
            auto_attack_uptime=1.0,
            one_rotation=True,
            score_only=True,
            target_health=5000.0,
        )
        assert full["breakdown"] == scored["breakdown"]
        assert full["total_damage"] == scored["total_damage"]
        assert full["resource_ledger"] == scored["resource_ledger"]

    def test_rider_row_score_parity(self):
        full = _fight(
            {"senna_mist_stacks": 40},
            duration=10.0,
            auto_attack_uptime=1.0,
            one_rotation=True,
            target_health=5000.0,
        )
        scored = _fight(
            {"senna_mist_stacks": 40},
            duration=10.0,
            auto_attack_uptime=1.0,
            one_rotation=True,
            score_only=True,
            target_health=5000.0,
        )
        assert _rider_row(full) is not None
        assert _rider_row(full) == _rider_row(scored)


# ---------------------------------------------------------------------------
# S11 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_mist_ledger_unchanged(self):
        # The souls ledger (P3) rides beside the rider: seeded 40,
        # kind souls, mana account intact — with and without autos.
        for uptime in (0.0, 1.0):
            result = _fight(
                {"senna_mist_stacks": 40}, duration=10.0, auto_attack_uptime=uptime
            )
            ledger = result["resource_ledger"]
            assert ledger["kind"] == "mana"
            souls = ledger.get("souls")
            assert souls is not None
            assert souls["kind"] == "souls"
            assert souls["opening_current"] == 40
            assert souls["declaration"]["name"] == ("Senna — Absolution (Mist souls)")

    def test_weakened_soul_pricing_unchanged(self):
        _, abilities = _parse({"senna_mist_stacks": 40})
        assert abilities["passive"]["on_hit"] == {
            "name": "Weakened Soul (mark consume)",
            "damage_per_hit": 100.0,
            "damage_type": "physical",
            "stacks_required": 2,
            "count_ability_hits": True,
        }
        # The mist stat buff is unchanged: +30 AD / +20% crit / +40 range.
        assert abilities["passive"]["stat_buff"] == {
            "bonus_attack_damage": 30.0,
            "critical_strike_chance": 20.0,
        }

    def test_q_w_r_damage_unchanged(self):
        # Rank-5 Q/W/R at 40 Mist stacks (bonus AD 70): the rider adds no
        # AD and must not touch these numbers.
        _, abilities = _parse({"senna_mist_stacks": 40})
        assert (
            abilities["Q"]["total_raw"]
            == pytest.approx(
                _resolve("Q", "Physical Damage", 4, {"bonus_attack_damage": 70.0})
            )
            == pytest.approx(172.0)
        )
        assert (
            abilities["W"]["total_raw"]
            == pytest.approx(
                _resolve("W", "Physical Damage", 4, {"bonus_attack_damage": 70.0})
            )
            == pytest.approx(293.0)
        )
        assert (
            abilities["R"]["total_raw"]
            == pytest.approx(
                _resolve("R", "Physical Damage", 2, {"bonus_attack_damage": 70.0})
            )
            == pytest.approx(630.5)
        )

    def test_item_on_hits_unchanged(self):
        # Kraken: the shared counter (4 autos + 1 Q application = 5 hits)
        # procs once; the mark still counts ability hits.  The rider (once
        # modeled) must not feed the item counter.
        result = _fight(
            {"senna_mist_stacks": 40},
            duration=5.0,
            auto_attack_uptime=1.0,
            items=[_item("Kraken Slayer")],
        )
        assert result["breakdown"]["on_hit_Kraken Slayer"]["count"] == 1
        assert result["breakdown"]["on_hit_Kraken Slayer"]["damage_type"] == "physical"
        assert result["breakdown"]["on_hit_ability_passive"]["count"] == 3
        # Q's applies_item_on_hits declaration is unchanged.
        _, abilities = _parse({"senna_mist_stacks": 40})
        assert abilities["Q"]["applies_item_on_hits"] == {
            "effectiveness": 1.0,
            "hits": 1,
            "triggers": ("on_hit", "on_attack"),
        }

    def test_vayne_w_consumer_untouched(self):
        # The engine's every-3rd-hit consumer (Vayne W) prices the same
        # procs from the same shared counter — the Senna rider must not
        # disturb it (a full fight, 8 autos -> 2 procs).
        stats = parse_stats(_LEVEL)
        abilities = parse_champion_abilities(
            get_champion("Vayne"),
            _LEVEL,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats=stats,
            target_stats={"target_max_health": 2000.0},
            champion_options={},
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000.0,
                target_armor=50,
                target_magic_resistance=40,
                fight_duration_seconds=10.0,
                auto_attack_uptime=1.0,
                deterministic=True,
                enforce_resource_limits=True,
                cast_order=[],
            ),
            champion_options={},
        )
        row = result["breakdown"]["on_hit_ability_W"]
        assert row["name"] == "Silver Bolts"
        assert row["count"] == 2  # 8 autos // 3
        assert row["damage_type"] == "true"
        assert row["unit"] == "procs"

    def test_corki_rider_seam_untouched(self):
        # Corki's per-auto TRUE rider (basic_attack_true_ratio) is the
        # closest engine seam to what Senna needs — it must stay exactly
        # as-is: one row, count == autos, true damage.
        stats = parse_stats(_LEVEL)
        abilities = parse_champion_abilities(
            get_champion("Corki"),
            _LEVEL,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats=stats,
            target_stats={"target_max_health": 2000.0},
            champion_options={},
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000.0,
                target_armor=50,
                target_magic_resistance=40,
                fight_duration_seconds=10.0,
                auto_attack_uptime=1.0,
                deterministic=True,
                enforce_resource_limits=True,
                cast_order=[],
            ),
            champion_options={},
        )
        row = result["breakdown"]["auto_attacks_true_damage"]
        assert row["name"] == "Hextech Munitions (true damage)"
        assert row["count"] == result["breakdown"]["auto_attacks"]["count"]
        assert row["damage_type"] == "true"


# ---------------------------------------------------------------------------
# S12 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list, then the Senna/mist/
# relic grep surface (contract 12):
#   .venv/bin/python -m pytest tests/test_senna_relic_cannon.py \
#     tests/test_senna_souls_ledger.py tests/test_mana_restore_refund.py \
#     tests/test_ezreal_w_mark_refund.py tests/test_jayce_w_mana_restore.py \
#     tests/test_resource_ledger.py tests/test_resource_ledger_consumers.py \
#     tests/test_resource_ledger_champion_consumers.py \
#     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#     tests/test_champion_options.py tests/test_vayne_q_reset.py \
#     tests/test_mundo_e_reset.py tests/test_darius_w_kill_refund.py \
#     tests/test_app.py
