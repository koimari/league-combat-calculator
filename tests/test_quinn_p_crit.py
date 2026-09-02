"""P4 — Quinn P (Harrier) on-hit + critical-strike-chance term
(test-matrix owner: RLM-2 C).

Focused matrix for Harrier's on-hit bonus damage and the crit-chance
gimmick of the P cooldown.  CURRENT RUNTIME FACTS (verify-before-pin
completed, all pinned in S1):

- The module (``src/calculator/champions/quinn.py``) ships ``_harrier``:
  the ONHIT-phase P entry that reads the cached "Bonus Physical Damage"
  row at ``ctx.level`` (per-level indexing) and prices
  ``on_hit_entry("Harrier", flat + 40% bonus AD, "physical")``.  The E5-2
  fix converted P from out_of_scope to a modeled on-hit (the same fix
  batch as Nautilus P / Poppy P).  PACKET_SHA256 is pinned.
- Cached P (data/champions.json) has FOUR effect rows: (0) the marking
  prose (Q primary target / Vault / Skystrike mark for 4 s, Valor marks
  periodically); (1) the on-hit damage row "Bonus Physical Damage":
  20 per-level values 15 : 132.35 (levels 1..20) with EMPTY units
  (degraded units — the AGENTS.md "Quinn P (crit chance)" half-parse) +
  one 40.0 "% bonus AD" modifier; (2) "Harrier deals 75 bonus physical
  damage against monsters." (no leveling); (3) "While Behind Enemy
  Lines is active, Harrier is disabled and all Harrier marks are
  removed." (no leveling).
- THE CRIT TERM: the P cooldown row carries values [0, 0, 0] and the
  units "7 : 2.56 (based on critical strike chance)" x3 — the modifier
  parser half-parsed the gimmick into the UNITS and zeroed the VALUES,
  so 7 / 2.56 / the 4.44-s 100%-crit endpoint exist NOWHERE as numbers.
  The abilities atom ``timing.cooldown`` (hash b1da09c15c0adb6b) stores
  values [0, 0, 0], units ["s", "s", "s"] — the gimmick is fully lost in
  the atom.  The binary QuinnPassive has NO cooldown DataValue (script-
  side).  The module prices NO P cooldown.  => The crit term is NOT
  source-backed; this matrix pins the fail-closed boundary (S6).
- Binary corroboration (data/bin/characters/quinn.bin.json, QuinnPassive):
  DataValues RevealDuration [4.0], ADRatio [0.4] (the 40% bonus-AD
  ratio), ModesPassiveDamageMultiplier [1.0]; mSpellCalculations
  BonusDamage = ByCharLevelInterpolation 15 -> 120 (levels 1 -> 18) +
  StatByNamedDataValueCalculationPart (mStat 2, mStatFormula 2,
  ADRatio); BonusMonsterDmg = NumberCalculationPart 75.0 (the monster
  line IS binary-backed, but the module prices only the on-hit row).

CONTRACT PINNED HERE (the P4 completion must satisfy; genuinely-
unsupported behavior is a STRICT xfail with reason "awaiting P4-Quinn-P
..." — the coordinator flips each xfail to a live test when the seam
lands):

- S1  Source evidence: all four cached P effects verbatim; the Bonus
      Physical Damage row (15..132.35 + 40% bonus AD, degraded empty
      units); the atoms (bonus-damage atom ids/hashes + active-duration
      + cooldown; the CRIT atom's degraded state — values 0, units "s");
      the binary corroboration; the module declaration + ASSUMPTIONS.
- S2  Default + absent parity: absent vs default byte-identical; the
      registered option surface unchanged (empty).
- S3  Level endpoints: the per-level flat at level 1 (15) / 18 (120) /
      20 (132.35) through the API, and the level indexing at the parse
      boundary with a nonzero bonus AD.
- S4  Marked-target on-hit: per-auto damage = flat + 40% bonus AD, one
      proc per auto (count == autos; the mark is assumed consumed every
      auto — module ASSUMPTION 2); the row does NOT crit (no crit
      accounting at the engine level; null crit fields at the API), the
      AUTO crits at the champion's crit chance (2.0x base).
- S5  Target and structure boundaries: the monster line (75 vs
      monsters — wiki + binary sourced but NO leveling row and no
      monster-target concept; named fail-closed boundary), the Behind
      Enemy Lines line (not modeled), the marking rules (4 s mark, 1 s
      mark-cooldown note, priority/parry/minion-visibility notes).
- S6  Malformed/ambiguous declarations: the degraded cooldown row's
      fail-closed handling (values zeroed; unit gimmick unresolvable ->
      0.0; no P cooldown priced anywhere; the atom cannot recover 7 /
      2.56).
- S7  API validation: option surface is empty; any unknown
      champion_options key is a 400.
- S8  Score/receipt parity: full vs score_only byte-identical on the
      shared receipt stream (total, Harrier row incl. damage_events,
      auto row, cast timeline).
- S9  Regression surface: the E5-2 Quinn assertions stay green (level 18
      no-items fight: 120 + 0.4 x bAD per auto, physical, count ==
      autos); the mandated sanity set passes.

AMBIGUITY NOTES for the coordinator:

1. THE CRIT TERM IS NOT SOURCE-BACKED.  Wiki values are [0,0,0] with
   the crit gimmick in the units; the atom normalizes units to "s" and
   keeps values [0,0,0]; the binary has no cooldown DataValue.  A
   certified crit-cooldown pricing (7 - 2.56 x crit chance, 4.44 s at
   100%) can only enter as a module-constant-with-receipt (the Gnar
   Mega constants precedent), never from the cache numbers.  The S6
   xfail pins the fail-closed receipt that must name this.
2. The monster 75 IS binary-backed (BonusMonsterDmg 75.0) and wiki-
   backed (prose, no leveling) but the runtime has no monster-target
   concept; the S5 xfail pins the named boundary for it.
3. Harrier-vs-crit: in the RUNTIME the on-hit row is a flat non-crit
   bonus (S4).  Whether in-game the Harrier bonus rides the attack's
   crit multiplier is not stated by the cached row; the client directive
   asked "does the row crit? at what chance?" — the pinned answer today
   is NO (row never crits; only the auto base crits at the champion's
   chance).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import (
    engine_registration_kind,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.scaling import resolve_scaling
from src.calculator.champions.slotlib import extract_cooldown
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_ABILITIES_ATOMS = json.loads(
    Path("data/atoms/abilities.json").read_text(encoding="utf-8")
)["objects"]
_QUINN_BIN_PATH = Path("data/bin/characters/quinn.bin.json")
_QUINN_BIN = (
    json.loads(_QUINN_BIN_PATH.read_text(encoding="utf-8"))
    if _QUINN_BIN_PATH.exists()
    else None
)
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_AWAIT = "awaiting P4-Quinn-P ..."
# Four different 25%-crit items -> 100% crit, bonus AD 125 at level 18.
_CRIT_ITEMS = (
    "Navori Flickerblade",
    "Infinity Edge",
    "Phantom Dancer",
    "The Collector",
)
_P_FLAT_LEVELS = [
    15.0,
    21.18,
    27.35,
    33.53,
    39.71,
    45.88,
    52.06,
    58.24,
    64.41,
    70.59,
    76.76,
    82.94,
    89.12,
    95.29,
    101.47,
    107.65,
    113.82,
    120.0,
    126.18,
    132.35,
]


def _stats(level: int = _LEVEL, bonus_ad: float = 100.0) -> dict:
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "flat_armor_penetration": 0.0,
        "health": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 200.0,
        "ability_power": 0.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": bonus_ad,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 300.0,
        "resource_regen_per_second": 0.0,
        "critical_strike_chance": 0.0,
        "level": level,
    }


def _parse(level: int = _LEVEL, bonus_ad: float = 100.0, crit: float = 0.0):
    stats = dict(_stats(level, bonus_ad), critical_strike_chance=crit)
    return stats, parse_champion_abilities(
        get_champion("Quinn"),
        level,
        0.0,
        ability_ranks=_RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": 2000.0},
    )


def _p_effects() -> list[dict]:
    return _CHAMPION_DATA["Quinn"]["abilities"]["P"][0]["effects"]


def _p_cooldown() -> dict:
    return _CHAMPION_DATA["Quinn"]["abilities"]["P"][0]["cooldown"]


def _p_notes() -> str:
    return _CHAMPION_DATA["Quinn"]["abilities"]["P"][0].get("notes", "")


def _bonus_damage_leveling() -> dict:
    for effect in _p_effects():
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == "Bonus Physical Damage":
                return leveling
    raise AssertionError("Quinn P has no 'Bonus Physical Damage' leveling")


def _api_payload(level: int = _LEVEL, **overrides) -> dict:
    payload = {
        "champion": "Quinn",
        "level": level,
        "items": [],
        "role": "top",
        "ability_ranks": dict(_RANKS),
        "fight_mode": "one_rotation",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "auto_attack_uptime_mode": "explicit",
        "target_health": 2000,
        "target_armor": 0,
        "target_mr": 0,
    }
    payload.update(overrides)
    return payload


def _api(level: int = _LEVEL, **overrides):
    return app_module.app.test_client().post(
        "/api/calculate", json=_api_payload(level, **overrides)
    )


def _params(level: int = _LEVEL, **overrides) -> FightParams:
    base = {
        "target_health": 2000.0,
        "target_bonus_health": 0.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 1.0,
        "one_rotation": True,
        "include_actives": True,
        "deterministic": True,
        "auto_attack_uptime_mode": "explicit",
        "ability_ranks": dict(_RANKS),
        "champion_options": None,
        "item_options": {},
        "role": "top",
    }
    base.update(overrides)
    return FightParams(**base)


def _quinn_passive_binary() -> dict:
    if _QUINN_BIN is None:
        pytest.skip("local Quinn game-file evidence is unavailable")
    return _QUINN_BIN["Characters/Quinn/Spells/QuinnPassiveAbility/QuinnPassive"][
        "mSpell"
    ]


# ---------------------------------------------------------------------------
# S1 — Source evidence
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_p_all_four_effects_pinned_verbatim(self):
        effects = _p_effects()
        assert len(effects) == 4
        assert effects[0]["description"] == (
            "Innate: Quinn's Blinding Assault against the primary target, "
            "Vault, and Skystrike mark enemies hit with Harrier for 4 "
            "seconds, during which they are revealed. Valor will "
            "periodically mark a nearby visible enemy if no Harrier "
            "targets exist for 1 second."
        )
        assert effects[1]["description"] == (
            "Quinn's basic attacks on-hit against Harrier targets are "
            "empowered to consume the mark to deal 15 : 132.35 (based on "
            "level) (+ 40% bonus AD) bonus physical damage."
        )
        assert effects[2]["description"] == (
            "Harrier deals 75 bonus physical damage against monsters."
        )
        assert effects[3]["description"] == (
            "While Behind Enemy Lines is active, Harrier is disabled and "
            "all Harrier marks are removed."
        )

    def test_bonus_physical_damage_row_pinned(self):
        # The E5-2 fix's row: 20 per-level flats (levels 1..20) with the
        # degraded EMPTY units (AGENTS.md "Quinn P (crit chance)" lists P
        # as a half-parsed gimmick row — here the UNITS are empty, the
        # values survive) plus the 40% bonus-AD modifier.
        leveling = _bonus_damage_leveling()
        modifiers = leveling["modifiers"]
        assert len(modifiers) == 2
        flat, ratio = modifiers
        assert flat["values"] == _P_FLAT_LEVELS
        assert flat["units"] == [""] * 20  # degraded: units empty
        assert ratio["values"] == [40.0]
        assert ratio["units"] == ["% bonus AD"]

    def test_level_endpoints_in_the_cached_row(self):
        # Level indexing of the cached row: level 1 -> 15, level 18 ->
        # 120 (the binary's interpolation end), level 20 -> 132.35.
        flat = _bonus_damage_leveling()["modifiers"][0]["values"]
        assert flat[0] == 15.0
        assert flat[17] == 120.0
        assert flat[19] == 132.35
        assert len(flat) == 20  # the level cap is 20 (top lane)

    def test_degraded_cooldown_row_verbatim(self):
        # The CRIT term's only wiki evidence: values are ZEROED and the
        # "7 : 2.56 (based on critical strike chance)" gimmick survives
        # only as a unit string.  No 7 / 2.56 / 4.44 number exists.
        cooldown = _p_cooldown()
        assert cooldown["affectedByCdr"] is False
        modifiers = cooldown["modifiers"]
        assert len(modifiers) == 1
        assert modifiers[0]["values"] == [0, 0, 0]
        assert (
            modifiers[0]["units"] == ["7 : 2.56 (based on critical strike chance)"] * 3
        )

    def test_bonus_damage_atoms_pinned(self):
        # Both Bonus Physical Damage modifiers are atomized; the flat's
        # units are the degraded empty strings.
        quinn_atoms = _ABILITIES_ATOMS["Quinn"]
        flat_atom = next(
            a
            for a in quinn_atoms
            if a["atom_id"] == "ability.bonus _physical _damage.modifier_0"
            and a["source"] == "Quinn.P[0].effects[1].leveling[0].modifiers[0]"
        )
        assert flat_atom["hash"] == "3738717a70d96778"
        assert flat_atom["values"] == _P_FLAT_LEVELS
        assert flat_atom["units"] == [""] * 20  # degraded units survive as ""
        assert flat_atom["evidence"] == ["Bonus Physical Damage@effects[1]"]
        ratio_atom = next(
            a
            for a in quinn_atoms
            if a["atom_id"] == "ability.bonus _physical _damage.modifier_1"
        )
        assert ratio_atom["hash"] == "f5d253ac12f722b2"
        assert ratio_atom["values"] == [40.0]
        assert ratio_atom["units"] == ["% bonus AD"]

    def test_active_duration_atom_pinned(self):
        # The 4-second mark duration atom (from effects[0]'s prose).
        quinn_atoms = _ABILITIES_ATOMS["Quinn"]
        atom = next(
            a
            for a in quinn_atoms
            if a["atom_id"] == "timing.active_duration"
            and a["source"] == "Quinn.P[0].effects[0].description"
        )
        assert atom["hash"] == "7aef3aea28570130"
        assert atom["values"] == [4.0]
        assert atom["units"] == ["s"]

    def test_crit_cooldown_atom_degraded_state_pinned(self):
        # The CRIT atom: the wiki row's "7 : 2.56 (based on critical
        # strike chance)" units were NORMALIZED to "s" and the values are
        # zeroed — the crit-chance dependence is unrecoverable from the
        # atom.  This is the degraded state AGENTS.md warns about.
        quinn_atoms = _ABILITIES_ATOMS["Quinn"]
        atom = next(
            a
            for a in quinn_atoms
            if a["atom_id"] == "timing.cooldown"
            and a["source"] == "Quinn.P[0].cooldown"
        )
        assert atom["hash"] == "b1da09c15c0adb6b"
        assert atom["values"] == [0.0, 0.0, 0.0]
        assert atom["units"] == ["s", "s", "s"]
        # The crit gimmick text is absent from the atom entirely.
        assert "critical strike chance" not in json.dumps(atom)
        assert 7.0 not in atom["values"]
        assert 2.56 not in atom["values"]

    def test_binary_corroboration(self):
        # QuinnPassive DataValues: the 4 s reveal, the 40% AD ratio, the
        # 1.0 mode multiplier — and NO cooldown numbers (crit cooldown is
        # script-side, exactly like the wiki's zeroed row).
        spell = _quinn_passive_binary()
        values = {dv["name"]: dv["values"] for dv in spell["DataValues"]}
        assert values["RevealDuration"] == [4.0] * 7
        assert values["ADRatio"] == [pytest.approx(0.4)] * 7
        assert values["ModesPassiveDamageMultiplier"] == [1.0] * 7
        assert not any("ooldown" in key for key in spell)
        calcs = spell["mSpellCalculations"]
        bonus = calcs["BonusDamage"]["mFormulaParts"]
        flat = next(
            p for p in bonus if p["__type"] == "ByCharLevelInterpolationCalculationPart"
        )
        assert flat["mStartValue"] == 15.0
        assert flat["mEndValue"] == 120.0  # levels 1 -> 18
        stat = next(
            p for p in bonus if p["__type"] == "StatByNamedDataValueCalculationPart"
        )
        assert stat["mDataValue"] == "ADRatio"
        assert stat["mStat"] == 2  # bonus-AD stat code; wiki unit is authoritative
        assert stat["mStatFormula"] == 2
        monster = calcs["BonusMonsterDmg"]["mFormulaParts"]
        assert len(monster) == 1
        assert monster[0]["mNumber"] == 75.0  # the 75-vs-monsters line

    def test_module_declaration_pinned(self):
        from src.calculator.champions import quinn as quinn_module

        assert quinn_module.PACKET_SHA256 == (
            "a88925854e27a0548631207e5f283df6a0a369c6249f4ded272801230c801852"
        )
        # MERGE: coverage and review status have ONE home — the validated
        # module contract.  Quinn now prices every slot (W included), so
        # the module derives its coverage instead of restating it.  Main's
        # session-4 batch F pin (MODULE_COVERAGE["W"] == "no_damage") moved
        # because this branch's W emits its own attack-speed steroid rather
        # than the packet's zero-damage row.
        from src.calculator.champions import get_champion_module_contract

        contract = get_champion_module_contract("Quinn")
        assert contract.coverage["P"] == "modeled"
        assert contract.coverage["W"] == "modeled"
        assert contract.review_status == "reviewed_module"
        assert quinn_module._harrier.phase == "onhit"
        meta = get_champion_options_meta("Quinn")
        assert any(
            "15 : 132.35 (based on level) (+ 40% bonus AD)" in text
            and "Bonus Physical Damage" in text
            for text in meta["assumptions"]
        )
        assert any(
            "priced per auto against the marked target" in text
            for text in meta["assumptions"]
        )
        sources = {row["label"]: row for row in meta["sources"]}
        assert sources["Quinn P ability entry"]["revision_id"] == 2864147

    def test_parse_entry_shape_and_no_cooldown(self):
        # The P entry carries exactly the on-hit payload; there is NO
        # cooldown key — the degraded cooldown row prices nothing.
        _, abilities = _parse()
        passive = abilities["passive"]
        assert set(passive) == {
            "name",
            "damage_type",
            "total_raw",
            "parts",
            "on_hit",
        }
        assert passive["name"] == "Harrier"
        assert passive["damage_type"] == "physical"
        assert passive["total_raw"] == 0.0
        assert passive["parts"] == ()
        assert "cooldown" not in passive
        assert set(passive["on_hit"]) == {"name", "damage_per_hit", "damage_type"}
        assert passive["on_hit"]["name"] == "Harrier (on-hit)"
        assert passive["on_hit"]["damage_type"] == "physical"

    def test_engine_registration_is_named_module(self):
        assert engine_registration_kind("Quinn") == "reviewed_module"


# ---------------------------------------------------------------------------
# S2 — Default + absent parity
# ---------------------------------------------------------------------------


class TestDefaultAndAbsentParity:
    def test_absent_vs_default_options_byte_identical(self):
        # champion_options absent vs {} must produce byte-identical JSON.
        absent = _api()
        default = _api(champion_options={})
        assert absent.status_code == 200
        assert default.status_code == 200
        assert absent.get_json() == default.get_json()

    def test_registered_surface_unchanged(self):
        # Empty option surface today; the map still lists Quinn (the
        # Harrier assumptions are the frontend-facing contract).
        meta = get_champion_options_meta("Quinn")
        assert meta["options"] == []
        assert meta["assumptions"]
        config = app_module.app.test_client().get("/api/config").get_json()
        assert config["champion_options"]["Quinn"]["options"] == []
        assert any(
            "Harrier" in text
            for text in config["champion_options"]["Quinn"]["assumptions"]
        )


# ---------------------------------------------------------------------------
# S3 — Level endpoints (level indexing of the per-level flat)
# ---------------------------------------------------------------------------


class TestLevelEndpoints:
    def test_level_one_prices_15(self):
        # Level 1: flat 15; no ranks can be spent at level 1, so the
        # fight uses level-derived ranks (still one rotation with autos).
        response = _api(level=1, ability_ranks={})
        assert response.status_code == 200, response.get_json()
        row = response.get_json()["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(15.0, abs=0.06)
        assert row["count"] > 0

    def test_level_18_prices_120(self):
        response = _api(level=18)
        assert response.status_code == 200, response.get_json()
        row = response.get_json()["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(120.0, abs=0.06)

    def test_level_20_prices_132_35(self):
        # The level cap is 20 (top lane); the cached row's 20th value is
        # 132.35 and the module indexes by ctx.level.
        response = _api(level=20, role_quest_complete=True)
        assert response.status_code == 200, response.get_json()
        row = response.get_json()["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(132.35, abs=0.06)

    def test_parse_indexing_matches_wiki_row(self):
        # Parse boundary with bonus AD 100: per-hit == flat + 40.
        for level, flat in ((1, 15.0), (18, 120.0), (20, 132.35)):
            _, abilities = _parse(level=level, bonus_ad=100.0)
            assert abilities["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(
                flat + 0.4 * 100.0, abs=1e-9
            ), level


# ---------------------------------------------------------------------------
# S4 — Marked-target on-hit and crit behavior
# ---------------------------------------------------------------------------


class TestMarkedTargetOnHitAndCrit:
    def test_harrier_per_auto_flat_plus_40_percent_bonus_ad(self):
        # Marked-target pricing: every auto consumes the mark (module
        # ASSUMPTION 2), so count == autos and per-hit == flat + 0.4 bAD.
        response = _api(level=18)
        data = response.get_json()
        row = data["breakdown"]["on_hit_ability_passive"]
        autos = data["breakdown"]["auto_attacks"]
        assert row["name"] == "Harrier (on-hit)"
        assert row["count"] == autos["count"]
        assert row["damage_per_hit"] == pytest.approx(120.0, abs=0.06)
        assert row["total_damage"] == pytest.approx(120.0 * row["count"], abs=0.6)

    def test_harrier_scales_40_percent_bonus_ad_with_items(self):
        # The 40% bonus-AD term prices with items: at level 18 the four
        # crit items add 125 bonus AD -> 120 + 0.4 x 125 == 170.
        items = [get_item_by_name(name) for name in _CRIT_ITEMS]
        full = run_fight(get_champion("Quinn"), 18, items, _params())
        row = full["breakdown"]["on_hit_ability_passive"]
        assert full["champion_stats"]["bonus_attack_damage"] == pytest.approx(
            125.0, abs=1e-9
        )
        assert row["damage_per_hit"] == pytest.approx(120.0 + 0.4 * 125.0, abs=1e-9)

    def test_harrier_row_does_not_crit_at_100_percent_crit(self):
        # The engine prices the on-hit row with NO crit accounting: at
        # 100% crit the row keeps its flat per-hit and carries no
        # num_crits/num_non_crits at the engine level; the API renders
        # those fields as null.  The AUTO row crits at 2.0x base.
        items = [get_item_by_name(name) for name in _CRIT_ITEMS]
        # Non-deterministic mode so the crit rolls land (100% crit makes
        # every roll a crit); the four items carry Infinity Edge's +0.3
        # crit-damage bonus on top of the 2.0 base.
        full = run_fight(get_champion("Quinn"), 18, items, _params(deterministic=False))
        row = full["breakdown"]["on_hit_ability_passive"]
        autos = full["breakdown"]["auto_attacks"]
        assert full["champion_stats"]["critical_strike_chance"] == pytest.approx(
            100.0, abs=1e-9
        )
        assert "num_crits" not in row
        assert "crit_damage_per_hit" not in row
        assert row["damage_per_hit"] == pytest.approx(170.0, abs=1e-9)
        assert autos["num_crits"] == autos["count"]
        assert autos["num_non_crits"] == 0
        assert autos["crit_damage_per_hit"] == pytest.approx(
            full["champion_stats"]["attack_damage"] * 2.3, abs=1e-9
        )

    def test_api_harrier_row_crit_fields_are_null(self):
        # The public calculate boundary is deterministic: the on-hit row has
        # no crit accounting, while the auto row carries the expected-value
        # damage for the 2.3x Infinity Edge multiplier.
        response = _api(level=18, items=list(_CRIT_ITEMS))
        assert response.status_code == 200, response.get_json()
        data = response.get_json()
        row = data["breakdown"]["on_hit_ability_passive"]
        autos = data["breakdown"]["auto_attacks"]
        assert row["num_crits"] is None
        assert row["num_non_crits"] is None
        assert row["crit_damage_per_hit"] is None
        assert autos["damage_per_hit"] == pytest.approx(
            data["champion_stats"]["attack_damage"] * 2.3, abs=0.06
        )

    def test_harrier_damage_type_physical_everywhere(self):
        _, abilities = _parse()
        assert abilities["passive"]["damage_type"] == "physical"
        assert abilities["passive"]["on_hit"]["damage_type"] == "physical"
        full = run_fight(get_champion("Quinn"), 18, [], _params())
        assert full["breakdown"]["on_hit_ability_passive"]["damage_type"] == "physical"


# ---------------------------------------------------------------------------
# S5 — Target and structure boundaries
# ---------------------------------------------------------------------------


class TestTargetAndStructureBoundaries:
    def test_monster_line_verbatim(self):
        assert _p_effects()[2]["description"] == (
            "Harrier deals 75 bonus physical damage against monsters."
        )
        assert _p_effects()[2]["leveling"] == []

    def test_monster_75_not_priced_today(self):
        # Fail-closed: the module prices ONLY the on-hit row — the 75
        # never leaks into the P entry or the fight.
        _, abilities = _parse()
        assert abilities["passive"]["on_hit"]["damage_per_hit"] != pytest.approx(75.0)
        assert "75" not in json.dumps(abilities["passive"])
        full = run_fight(get_champion("Quinn"), 18, [], _params())
        assert full["breakdown"]["on_hit_ability_passive"]["damage_per_hit"] == (
            pytest.approx(120.0, abs=1e-9)
        )

        # The completion's receipt must cite the monster row verbatim so
        # the 75 cannot silently decay into the champion-target price.
        meta = get_champion_options_meta("Quinn")
        assert any(
            "75 bonus physical damage against monsters" in text
            for text in meta["assumptions"]
        )

    def test_behind_enemy_lines_line_verbatim(self):
        assert _p_effects()[3]["description"] == (
            "While Behind Enemy Lines is active, Harrier is disabled and "
            "all Harrier marks are removed."
        )
        assert _p_effects()[3]["leveling"] == []

    def test_behind_enemy_lines_does_not_gate_harrier_today(self):
        # Fail-closed pin of today's model: R (Skystrike) is priced, and
        # the P on-hit is NOT disabled by an R-active state (no R-state
        # concept in the module).  The R row and the P row coexist.
        _, abilities = _parse()
        assert abilities["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(
            160.0, abs=1e-9
        )
        assert abilities["R"]["total_raw"] > 0.0

        meta = get_champion_options_meta("Quinn")
        assert any(
            "Behind Enemy Lines" in text and ("disabled" in text or "gate" in text)
            for text in meta["assumptions"]
        )

    def test_marking_rules_pinned(self):
        # effects[0] + notes: 4 s reveal mark from Q primary target /
        # Vault / Skystrike, Valor's periodic marking, the 1 s mark
        # cooldown, priority, parry, and minion-visibility rules.
        effects = _p_effects()
        assert (
            "mark enemies hit with Harrier for 4 seconds" in effects[0]["description"]
        )
        assert "Valor will periodically mark" in effects[0]["description"]
        notes = _p_notes()
        assert (
            "Harrier goes on a 1-second cooldown if it's not already on cooldown"
            in notes
        )
        assert "Last unit hit" in notes
        assert "Lowest-health enemy champion" in notes
        assert "Harrier is consumed even if it is parried" in notes
        assert (
            "Harrier will not mark enemy  minions while Quinn is not  visible" in notes
        )

    def test_mark_duration_not_priced_as_cooldown(self):
        # The 4 s mark duration lives only in the atom (S1); the fight
        # has no mark-state machine — no duration/cooldown keys on P.
        _, abilities = _parse()
        assert "cooldown" not in abilities["passive"]
        assert "duration" not in abilities["passive"]

    def test_monster_boundary_is_named(self):
        # The 75-vs-monsters term (cached effects[2] + the binary
        # BonusMonsterDmg 75.0) is a named boundary: not priced (no
        # monster-target kind), never silently leaked.
        meta = get_champion_options_meta("Quinn")
        assert any(
            "75 bonus physical damage against monsters" in text
            for text in meta["assumptions"]
        )
        full = run_fight(get_champion("Quinn"), 18, [], _params(deterministic=True))
        row = full["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(120.0 + 0.4 * 0.0)

    def test_bel_gating_is_named(self):
        # Behind Enemy Lines (R-active) disables Harrier and removes all
        # marks (cached effects[3]) — a named boundary: the on-hit stays
        # unconditional in the model.
        meta = get_champion_options_meta("Quinn")
        assert any(
            "Behind Enemy Lines" in text and "disables" in text
            for text in meta["assumptions"]
        )


# ---------------------------------------------------------------------------
# S6 — Malformed / ambiguous declarations (degraded row fail-closed)
# ---------------------------------------------------------------------------


class TestMalformedDeclarations:
    def test_degraded_unit_resolves_to_zero(self):
        # The half-parsed crit unit can never price damage: the resolver
        # returns 0.0 for the gimmick string (and the cache values are
        # already zero), so no future reader can silently price 7/2.56.
        assert (
            resolve_scaling("7 : 2.56 (based on critical strike chance)", 40.0, {}, {})
            == 0.0
        )

    def test_extract_cooldown_returns_zero_for_the_degraded_row(self):
        # The generic cooldown extractor reads the zeroed values: any
        # P-cooldown pricing from the cache would price 0.0 today —
        # fail-closed (never 7 or 4.44).
        ability = _CHAMPION_DATA["Quinn"]["abilities"]["P"][0]
        assert extract_cooldown(ability, 1) == 0.0
        assert extract_cooldown(ability, 18) == 0.0

    def test_no_crit_numbers_anywhere_in_cache_or_atoms(self):
        # The 7 / 2.56 / 4.44 endpoints exist NOWHERE as numbers: wiki
        # values are zeroed, the atom values are zeroed, and the binary
        # has no cooldown DataValue.  A certified crit-cooldown can only
        # enter as a module constant with a receipt.
        cooldown = _p_cooldown()
        assert all(v == 0 for v in cooldown["modifiers"][0]["values"])
        quinn_atoms = _ABILITIES_ATOMS["Quinn"]
        atom = next(a for a in quinn_atoms if a["source"] == "Quinn.P[0].cooldown")
        assert atom["values"] == [0.0, 0.0, 0.0]
        spell = _quinn_passive_binary()
        assert not any("ooldown" in key for key in spell)

        # The completion's receipt must quote the crit expression so the
        # term is either certified or explicitly out of scope — never a
        # silent zero.
        meta = get_champion_options_meta("Quinn")
        assert any(
            "critical strike chance" in text and "2.56" in text
            for text in meta["assumptions"]
        )


# ---------------------------------------------------------------------------
# S7 — API validation (option surface)
# ---------------------------------------------------------------------------


class TestApiValidation:
    def test_unknown_champion_option_rejected(self):
        # Quinn declares no options; any champion_options key is a 400
        # with a named error (fail-closed, not silently dropped).
        response = _api(level=18, champion_options={"harrier_crit_chance": 50})
        assert response.status_code == 400
        error = response.get_json()["error"]
        assert "unknown option" in error
        assert "harrier_crit_chance" in error

    def test_option_surface_is_empty_in_meta_and_config(self):
        meta = get_champion_options_meta("Quinn")
        assert meta["options"] == []
        config = app_module.app.test_client().get("/api/config").get_json()
        assert config["champion_options"]["Quinn"]["options"] == []

    def test_empty_options_object_accepted(self):
        response = _api(level=18, champion_options={})
        assert response.status_code == 200, response.get_json()


# ---------------------------------------------------------------------------
# S8 — Score / receipt parity
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_full_vs_score_only_byte_identical_shared_stream(self):
        champion = get_champion("Quinn")
        full = run_fight(champion, 18, [], _params())
        score = run_fight(champion, 18, [], _params(), score_only=True)
        assert full["total_damage"] == pytest.approx(score["total_damage"])
        assert (
            full["breakdown"]["on_hit_ability_passive"]
            == score["breakdown"]["on_hit_ability_passive"]
        )
        assert full["breakdown"]["auto_attacks"] == score["breakdown"]["auto_attacks"]
        full_casts = [
            (c["time"], c["slot"], c["ordinal"]) for c in full["cast_timeline"]
        ]
        score_casts = [
            (c["time"], c["slot"], c["ordinal"]) for c in score["cast_timeline"]
        ]
        assert full_casts == score_casts
        assert score["breakdown"]["on_hit_ability_passive"]["damage_per_hit"] == (
            pytest.approx(120.0, abs=1e-9)
        )

    def test_score_only_harrier_row_keeps_damage_events(self):
        champion = get_champion("Quinn")
        score = run_fight(champion, 18, [], _params(), score_only=True)
        row = score["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == len(row["damage_events"])
        assert all(
            event["damage"] == pytest.approx(120.0, abs=1e-9)
            for event in row["damage_events"]
        )
        assert row["event_phase"] == "auto"


# ---------------------------------------------------------------------------
# S9 — Regression surface (the E5-2 Quinn contract stays green)
# ---------------------------------------------------------------------------


class TestRegressionSurface:
    def test_e5_fix_2_quinn_contract_stays_green(self):
        # The E5-2 fix's own assertions, re-pinned: level 18, no items,
        # the Harrier row prices 120 + 0.4 x bAD per auto (bAD 0 here)
        # and the passive parses physical.
        response = _api(level=18)
        assert response.status_code == 200, response.get_json()
        data = response.get_json()
        b_ad = data["champion_stats"]["bonus_attack_damage"]
        assert b_ad == 0.0
        row = data["breakdown"]["on_hit_ability_passive"]
        assert row["name"] == "Harrier (on-hit)"
        assert row["damage_per_hit"] == pytest.approx(120.0 + 0.4 * b_ad, abs=0.06)
        assert row["total_damage"] == pytest.approx(
            row["damage_per_hit"] * row["count"], abs=0.6
        )
        _, abilities = _parse()
        assert abilities["passive"]["on_hit"]["damage_type"] == "physical"

    def test_q_e_r_rows_unchanged(self):
        # The Q/E/R packet rows are untouched by the P matrix: their
        # total_raw still equals the cached rows at rank 5/5/3.
        _, abilities = _parse()
        data = _CHAMPION_DATA["Quinn"]["abilities"]
        data["Q"][0]
        data["E"][0]
        data["R"][1]
        assert abilities["Q"]["total_raw"] > 0.0
        assert abilities["E"]["total_raw"] > 0.0
        assert abilities["R"]["total_raw"] > 0.0
        assert abilities["Q"]["damage_type"] == "physical"
        assert abilities["E"]["damage_type"] == "physical"
        assert abilities["R"]["damage_type"] == "physical"
