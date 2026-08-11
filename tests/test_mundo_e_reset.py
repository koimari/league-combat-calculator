"""P4 Dr. Mundo E (Blunt Force Trauma) — attack-reset throughput
(test-matrix owner: RLM-2 C).

Focused TDD matrix for the sourced attack-reset throughput contract.
CURRENT RUNTIME FACTS (verify-before-pin completed against
``src/calculator/champions/dr_mundo.py``, ``src/calculator/damage.py``,
``data/champions.json`` and ``data/atoms/abilities.json``):

- The registered champion name is ``"Dr. Mundo"`` (the module's parser
  name; ``get_champion("DrMundo")["name"] == "Dr. Mundo"``) while the
  CACHE key and the atoms-catalog key are ``"DrMundo"``.  The module's
  ``_blunt_force_trauma`` is the E slot: ONE entry carrying BOTH the
  %max-health passive AD steroid (``stat_buff``: Bonus Attack Damage
  2/2.3/2.6/2.9/3.2 % maximum health -> 151.0504 at the reference build)
  and the empowered-auto active (Minimum Bonus Physical Damage
  5/15/25/35/45 + 5% bonus health, missing-health amp 0-40% capping at
  70% missing, stamped ``empowers_next_auto: True`` so casts are capped
  at the auto count; with no auto stream each cast forces its own swing
  — the Blitzcrank/Caitlyn rule).  The ASSUMPTIONS record "it resets the
  attack timer, which is not modeled as extra attacks".
- E is HEALTH-costed (10/25/40/55/70) with cooldown 9/8.25/7.5/6.75/6
  (affectedByCdr); rank 5 at the reference build's 0 haste = 6.0s.
  ``resource_cost`` is absent from the parsed entry (only MANA/ENERGY
  costs are modeled).
- The cached E data carries four effects: the passive prose, the active
  empower prose (4s window + "increased by 0% : 40% (based on Dr. Mundo's
  missing health)"), the 140% minion/monster line, and the reset prose
  ("Blunt Force Trauma resets Dr. Mundo's basic attack timer.") with NO
  leveling — so the reset has no atom.  E's atoms are 14 rows total: the
  passive AD modifier, the four Minimum/Maximum Bonus Physical Damage
  modifiers (flat + % bonus health), the eight minion/monster rows and
  the cooldown.  E-SPECIFIC DEVIATION FROM VAYNE Q: there is NO
  ``timing.active_duration`` atom for E — the atomizer's duration scan
  only reads ``effects[0]`` and E's effects[0] is the PASSIVE (no
  duration prose), so the 4s empower window lives only in effects[1]
  prose (Vayne Q's window sits in effects[0] and IS atomized).
- The P4-Mundo-E coordinator's completion adds the SMALLEST opt-in
  contract for that throughput, following the P4-Vayne-Q template: an
  ``e_reset_throughput`` bool option (default False) that, when on,
  treats each accepted E cast as an attack reset — the empowered swing
  fires immediately (zero dead time) and BUYS one extra swing on top of
  the ambient auto stream.  Default fights and every registered fight
  stay byte-identical when the option is absent or False.  Genuinely
  absent mechanics are ``xfail`` with reason
  "awaiting P4-Mundo-E wiring"; the completion removes the markers and
  reconciles any pin it disagrees with.

CONTRACT SEMANTICS PINNED HERE (Model A — extra autos, the Vayne-Q
template): the ordinary auto stream is untouched (floor(AS x duration x
uptime)) and every accepted E cast adds one reset swing; total swings =
ordinary autos + E casts.  In the 10s reference fight the cooldown grid
only admits 2 E casts either way (rank-5 cd 6.0s: 0.25 + 6.25; the next
cast lands at 12.25), so unlike Vayne Q the ambient-auto cap does NOT
bind — the observable delta of the option is purely the two bought
swings on the auto row.  Flagged for the coordinator in the S4 header.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + atoms + module declaration: the cached E
      effects verbatim (passive prose, active empower prose with the 4s
      window + missing-health amp, the 140% minion/monster line, the
      reset prose), Minimum Bonus Physical Damage 5/15/25/35/45 + % bonus
      health, the HEALTH cost 10/25/40/55/70, the cooldown
      9/8.25/7.5/6.75/6 (affectedByCdr), the atoms (passive AD, minimum
      bonus flat, minimum bonus % health, cooldown ids/hashes; the
      ACTIVE-DURATION atom ABSENCE — the E-specific deviation; the
      reset-atom absence), the module's ``_blunt_force_trauma`` /
      OPTIONS / ASSUMPTIONS declaration.
  S2  Empowered-auto baseline (unchanged by the reset contract): the
      passive steroid + the empowered bonus coexist on ONE E entry
      (stat_buff 151.0504 AND empowers_next_auto True), the amp pin
      169.8571.. at 30% missing, the 6.0s cooldown, the per-swing
      damage pricing on and off the option.
  S3  The option contract: the ``e_reset_throughput`` option (meta +
      central rotation classification), the parse-level payload switch
      when on (empowers_next_auto becomes the self-supplying dict while
      the stat_buff SURVIVES — the E-specific coexistence pin), the
      strict fail-closed read (junk values fall back to the default),
      absent-vs-False default parity on the direct engine AND the
      pipeline registered-fight surface.
  S4  Opted-in reset schedule (Model A): with the option on the E casts
      stay on the cooldown grid (2 casts at 0.25/6.25 — the cap does not
      bind at cd 6s), each cast buys one extra swing (auto row 8 -> 10),
      and the damage delta from the reference fight — exact times /
      counts / damage pinned.
  S5  One-rotation + zero-auto interplay: no auto stream -> no reset
      effect (forced-swing rule unchanged, byte-identical with the
      option on); one-rotation with an auto stream -> the single cast
      buys one extra swing (Model A pin, flagged for the coordinator).
  S6  Score/receipt parity: the scored surface is byte-identical full
      vs score_only today and must stay so on the opted-in schedule.
  S7  Unchanged boundaries: the passive steroid, the missing-health amp,
      the W charge ticks (12-tick charge + detonation row), Q/R, other
      champions, control events.
  S8  Fail-closed: the API boundary rejects unknown keys today and
      non-bool values once the option is declared; the option never
      silently no-ops when on (S4 pins).
  S9  Regression surface: ``tests/test_dr_mundo.py`` stays green plus the
      mandated sanity set (run list in the module footer).

Expected values are recomputed from ``data/champions.json`` rows, the
live atomization and the module's own typed extractor — no literal
damage constants beyond the sourced cost 10/25/40/55/70, the sourced
cooldown grid and the reference build's own stats.
"""

import copy
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.atomizer_domains import atomize_abilities
from src.calculator.champions import (
    get_champion_option_rotation,
    get_champion_options_meta,
    parse_champion_abilities,
    registered_champion_names,
)
from src.calculator.champions import dr_mundo as dr_mundo_module
from src.calculator.damage import (
    FightConfig,
    _empower_burst_attack_speed,
    _empower_hits,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight

_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_PATH = _ROOT / "data" / "atoms" / "abilities.json"

# The registered champion name (the module's parser name); the cache key
# and the atoms-catalog key are the exact cached name "DrMundo".
CHAMPION = "Dr. Mundo"
DATA_KEY = "DrMundo"
CATALOG_KEY = "DrMundo"
# The P4-Mundo-E coordinator wires the opt-in reset contract; genuinely
# absent mechanics are xfailed with this reason.
_AWAIT = "awaiting P4-Mundo-E wiring"

# The contract option key (the "smallest opt-in" reset-throughput
# control; the coordinator's completion declares it — key proposal,
# flagged in the reply for confirmation).
OPTION_KEY = "e_reset_throughput"

# Sourced E values (cached rows, pinned in S1).
E_COST = [10.0, 25.0, 40.0, 55.0, 70.0]
E_COOLDOWNS = [9.0, 8.25, 7.5, 6.75, 6.0]
# The cached E atoms (data/atoms/abilities.json + live atomization).
# NOTE: there is NO timing.active_duration atom — the 4s empower window
# lives in effects[1] prose and the atomizer only scans effects[0] (the
# passive) for a prose duration.  The reset prose (effects[3]) has no
# leveling, so it has no atom either.
E_ATOMS = {
    "passive_ad": (
        "ability.bonus _attack _damage",
        "51d0a2ca5a739a6f",
        [2.0, 2.3, 2.6, 2.9, 3.2],
    ),
    "minimum_flat": (
        "ability.minimum _bonus _physical _damage.modifier_0",
        "aeba0d1d15c0cb94",
        [5.0, 15.0, 25.0, 35.0, 45.0],
    ),
    "minimum_pct": (
        "ability.minimum _bonus _physical _damage.modifier_1",
        "af89da91c67dfe21",
        [5.0] * 5,
    ),
    "cooldown": ("timing.cooldown", "9869fb3d76a36103", E_COOLDOWNS),
}

# Reference build (test_dr_mundo.py's setup): level 18, Q/W/E rank 5,
# R rank 3, base health 2391 + 2000 bonus health, base AD 104, AS 1.0
# (ratio 0.625), 0 ability haste, 100 armor / 50 MR, missing health 30%
# (the OPTIONS default).  Fight: 2400 HP target, 100 armor / 100 MR,
# 10 seconds, 100% auto uptime.
_LEVEL = 18
_BASE_HEALTH = 2391.0
_BONUS_HEALTH = 2000.0
_MAX_HEALTH = _BASE_HEALTH + _BONUS_HEALTH
_BASE_AD = 104.0
_DURATION = 10.0
_TARGET_HEALTH = 2400.0
# R rank 3 @30% missing: 25% x 30% x 4391 = 329.325 base health -> the
# parse's E passive reads 0.032 x 4720.325 = 151.0504 bonus AD.
_R_GRANT = 0.25 * _MAX_HEALTH * 0.30  # 329.325
_E_AD_BUFF = 0.032 * (_MAX_HEALTH + _R_GRANT)  # 151.0504
_ENGINE_AD = _BASE_AD + _E_AD_BUFF  # 255.0504
# E bonus at the reference build: (45 + 5% x 2000) x amp(30% missing);
# amp = 1 + 0.4 x (30/70) = 1.17142857...
_E_BONUS_RAW = (45.0 + 0.05 * _BONUS_HEALTH) * (1.0 + 0.4 * 30.0 / 70.0)
_E_CD = 6.0  # rank 5, 0 haste
# Auto per-hit after 100 armor; E per-swing = auto hit + E bonus.
_AUTO_HIT = _ENGINE_AD * 100.0 / 200.0  # 127.5252
_E_SWING = _AUTO_HIT + _E_BONUS_RAW * 100.0 / 200.0  # 212.45377142857143
# Direct-engine reference fight pins (10s, uptime 1.0).
_OFF_AUTOS = 8  # floor(1.0 x 10) = 10 swings, 2 ride the E row
_ON_AUTOS = 10  # 10 ordinary + 2 reset swings (Model A)
_E_CAST_TIMES = [0.25, 6.25]  # cooldown grid (Q's 0.25 cast_time shifts E)
_OFF_TOTAL = 2601.209142857143
_ON_TOTAL = 2856.259542857143
_ZERO_UPTIME_TOTAL = 1581.007542857143
_ONE_ROT_OFF_TOTAL = 1950.1805714285714
_ONE_ROT_ON_TOTAL = 2077.7057714285716


def _stats() -> dict:
    """The reference build's explicit stat packet (direct engine)."""
    return {
        "level": float(_LEVEL),
        "health": _MAX_HEALTH,
        "bonus_health": _BONUS_HEALTH,
        "base_attack_damage": _BASE_AD,
        "bonus_attack_damage": 0.0,
        "attack_damage": _BASE_AD,
        "ability_power": 0.0,
        "armor": 100.0,
        "magic_resistance": 50.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "ability_haste": 0.0,
        "basic_ability_haste": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "lethality": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "max_mana": 500.0,
        "bonus_mana": 0.0,
        "is_melee": True,
    }


def _parse(options: dict | None = None) -> tuple[dict, dict]:
    """Parse the reference build; the BUFF-phase R re-prices E's passive
    at parse time (the module's R -> max health -> E bonus AD chain), so
    E's stat_buff already carries the +151.0504 pin."""
    stats = _stats()
    abilities = parse_champion_abilities(
        get_champion(DATA_KEY),
        _LEVEL,
        0.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats=dict(stats),
        target_stats={"target_max_health": _TARGET_HEALTH},
        champion_options=options,
    )
    return stats, abilities


def _fight(
    options: dict | None = None,
    *,
    duration: float = _DURATION,
    one_rotation: bool = False,
    auto_attack_uptime: float = 1.0,
    score_only: bool = False,
    **overrides,
) -> dict:
    """Direct-engine fight at the reference build (explicit stats)."""
    stats, abilities = _parse(options)
    config = {
        "target_health": _TARGET_HEALTH,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": duration,
        "auto_attack_uptime": auto_attack_uptime,
        "one_rotation": one_rotation,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(
        dict(stats),
        abilities,
        [],
        FightConfig(**config),
        score_only=score_only,
        champion_options=options,
    )


def _pipeline_fight(
    options: dict | None = None,
    *,
    score_only: bool = False,
    **overrides,
) -> dict:
    """Pipeline fight (real champion stats) for the registered surface.

    ``auto_attack_uptime=1.0`` rides the legacy mode (the explicit value
    is honored), so the pipeline surface is directly comparable to the
    direct-engine reference fight (AS 1.020625 at level 18 -> floor(10.2)
    = 10 swings; 2 ride the E row -> auto row 8)."""
    params = dict(
        target_health=_TARGET_HEALTH,
        target_armor=100.0,
        target_magic_resistance=100.0,
        fight_duration_seconds=_DURATION,
        auto_attack_uptime=1.0,
        one_rotation=False,
        deterministic=True,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options=options or {},
    )
    params.update(overrides)
    return run_fight(
        copy.deepcopy(get_champion(DATA_KEY)),
        _LEVEL,
        [],
        FightParams(**params),
        score_only=score_only,
    )


def _json(result: dict) -> str:
    """Deterministic JSON-ish fingerprint for byte-identity comparisons."""
    return json.dumps(result, sort_keys=True, default=lambda o: f"<{type(o).__name__}>")


def _e_times(result: dict) -> list[float]:
    return [c["time"] for c in result["cast_timeline"] if c["slot"] == "E"]


def _approx_times(times: list[float]) -> list:
    return [pytest.approx(t, abs=1e-6) for t in times]


# ---------------------------------------------------------------------------
# S1 — Source evidence, atoms, module declaration
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_e_effects_carry_the_passive_empower_minion_and_reset_prose(
        self,
    ) -> None:
        """The cached E data carries all four effects verbatim: the
        passive steroid prose (effects[0], % maximum health 2..3.2), the
        active empower prose with the 4s window + the missing-health amp
        (effects[1]), the 140% minion/monster line (effects[2]), and the
        reset prose (effects[3]) with NO leveling (so no atom can exist
        for it)."""
        e = get_champion(DATA_KEY)["abilities"]["E"][0]
        assert e["effects"][0]["description"] == (
            "Passive: Dr. Mundo gains bonus attack damage."
        )
        assert e["effects"][0]["leveling"][0]["modifiers"][0]["values"] == [
            2,
            2.3,
            2.6,
            2.9,
            3.2,
        ]
        assert (
            e["effects"][0]["leveling"][0]["modifiers"][0]["units"]
            == ["% maximum health"] * 5
        )
        assert e["effects"][1]["description"] == (
            "Active: Dr. Mundo empowers his next basic attack within 4 "
            "seconds to have an uncancellable windup, gain 50 bonus range, "
            "and deal bonus physical damage, increased by 0% : 40% (based "
            "on Dr. Mundo's missing health). If the target dies or is a "
            "small monster, they are sent flying away in a line, though "
            "not through terrain, causing all enemies they pass through to "
            "take 100% AD physical damage plus Blunt Force Trauma's "
            "minimum bonus damage."
        )
        assert e["effects"][2]["description"] == (
            "Blunt Force Trauma as well as the triggering attack's damage "
            "is increased to 140% against minions and 140% against "
            "monsters."
        )
        assert e["effects"][3]["description"] == (
            "Blunt Force Trauma resets Dr. Mundo's basic attack timer."
        )
        assert e["effects"][3]["leveling"] == []  # no leveling -> no atom

    def test_e_cost_is_health_and_cooldown_is_sourced(self) -> None:
        """Cost 10/25/40/55/70 HEALTH; cooldown 9/8.25/7.5/6.75/6,
        affected by CDR; PHYSICAL_DAMAGE, auto-targeted, HEALTH resource."""
        e = get_champion(DATA_KEY)["abilities"]["E"][0]
        assert e["cost"]["modifiers"][0]["values"] == [10, 25, 40, 55, 70]
        assert e["cooldown"]["modifiers"][0]["values"] == [9, 8.25, 7.5, 6.75, 6]
        assert e["cooldown"]["affectedByCdr"] is True
        assert e["resource"] == "HEALTH"
        assert e["damageType"] == "PHYSICAL_DAMAGE"
        assert e["targeting"] == "Auto"

    def test_minimum_bonus_physical_damage_leveling_is_flat_plus_bonus_health(
        self,
    ) -> None:
        """The active's minimum bonus is 5/15/25/35/45 flat plus 5%
        bonus health at every rank (effects[1], leveling[0])."""
        e = get_champion(DATA_KEY)["abilities"]["E"][0]
        leveling = e["effects"][1]["leveling"][0]
        assert leveling["modifiers"][0]["values"] == [5, 15, 25, 35, 45]
        assert leveling["modifiers"][0]["units"] == [""] * 5
        assert leveling["modifiers"][1]["values"] == [5] * 5
        assert leveling["modifiers"][1]["units"] == ["% bonus health"] * 5

    def test_e_atom_rows_and_the_two_absences(self) -> None:
        """The catalog and the live atomization agree on exactly the
        E rows (14: passive AD, four Minimum/Maximum Bonus Physical
        Damage modifiers, eight minion/monster modifiers, cooldown).

        TWO atom absences, both E-specific:
        - NO ``timing.active_duration`` row: the 4s empower window lives
          in effects[1] prose, but the atomizer's duration scan only
          reads effects[0] — and E's effects[0] is the PASSIVE.  (Vayne
          Q's 3s window sits in effects[0] and IS atomized; E differs.)
        - NO row sources effects[3]: the reset prose has no leveling, so
          the reset is a typed rule declaration, not a leveling row."""
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        catalog_e = [
            r
            for r in catalog["objects"][CATALOG_KEY]
            if r["source"].startswith(f"{CATALOG_KEY}.E[")
        ]
        live_e = list(atomize_abilities(CATALOG_KEY, get_champion(DATA_KEY))["E"])
        assert len(catalog_e) == len(live_e) == 14
        for row in catalog_e + live_e:
            assert "effects[3]" not in row["source"], row["source"]
            assert row["atom_id"] != "timing.active_duration", row["source"]
        assert not any(
            row["atom_id"] == "timing.active_duration"
            for row in catalog["objects"][CATALOG_KEY]
            if row["source"].startswith(f"{CATALOG_KEY}.E[")
        )
        by_id = {row["atom_id"]: row for row in catalog_e}
        for key, (atom_id, hash_, values) in E_ATOMS.items():
            assert by_id[atom_id]["hash"] == hash_, key
            assert by_id[atom_id]["values"] == values, key
        live_by_id = {row["atom_id"]: row for row in live_e}
        for atom_id in by_id:
            assert live_by_id[atom_id]["values"] == by_id[atom_id]["values"]

    def test_module_declares_the_blunt_force_trauma_slot(self) -> None:
        """The module's SLOTS map E to _blunt_force_trauma, the parser is
        built for the exact registered name "Dr. Mundo" (the cache key is
        "DrMundo"), and the option surface today is exactly the two
        declared options (the pre-contract declaration)."""
        assert dr_mundo_module.SLOTS["E"] is dr_mundo_module._blunt_force_trauma
        assert dr_mundo_module.parse_abilities is not None
        assert get_champion(DATA_KEY)["name"] == CHAMPION
        meta = get_champion_options_meta(CHAMPION)
        assert [o["key"] for o in meta["options"]] == [
            "mundo_missing_health_percent",
            "r_nearby_champions",
            "e_reset_throughput",
        ]
        assert any(
            "e_reset_throughput" in text and "Trait_AttackReset" in text
            for text in meta["assumptions"]
        )
        assert not any(
            "resets the attack timer, which is not modeled as extra attacks" in text
            for text in meta["assumptions"]
        )


# ---------------------------------------------------------------------------
# S2 — Empowered-auto baseline (unchanged by the reset contract)
# ---------------------------------------------------------------------------


class TestEmpoweredAutoBaseline:
    def test_e_is_one_entry_with_steroid_and_empower_side_by_side(self) -> None:
        """E's ONE entry carries BOTH the passive %max-health AD steroid
        (stat_buff 151.0504, feeding the auto hit) and the empowered
        active (169.8571.. bonus, one attack per cast — the Alistar
        rule).  The reset contract must never split or drop either half
        (the E-specific coexistence pin)."""
        _, abilities = _parse()
        e = abilities["E"]
        assert e["rank"] == 5
        assert e["damage_type"] == "physical"
        assert e["stat_buff"] == {"bonus_attack_damage": pytest.approx(_E_AD_BUFF)}
        assert e["total_raw"] == pytest.approx(_E_BONUS_RAW, abs=1e-9)
        assert e["parts"][0].amount == pytest.approx(_E_BONUS_RAW, abs=1e-9)
        assert e["empowers_next_auto"] is True
        assert _empower_hits(e["empowers_next_auto"]) == 1
        assert e["cooldown"] == pytest.approx(_E_CD, abs=1e-9)
        assert e.get("resource_cost") is None  # HEALTH costs are not modeled

    def test_the_4s_window_is_prose_only_and_the_amp_caps_at_70_percent(
        self,
    ) -> None:
        """The window is sourced prose ("within 4 seconds", effects[1]) —
        never an atom (S1).  The amp prose "0% : 40% (based on Dr. Mundo's
        missing health)" resolves through the module's E_MAX_* constants
        and the 70% cap; the reference 30% missing yields
        1.17142857... x (45 + 5% x 2000)."""
        e = get_champion(DATA_KEY)["abilities"]["E"][0]
        assert "within 4 seconds" in e["effects"][1]["description"]
        assert "0% : 40%" in e["effects"][1]["description"]
        assert dr_mundo_module.E_MAX_DAMAGE_AMP == 0.4
        assert dr_mundo_module.E_MAX_AMP_MISSING_HEALTH_PERCENT == 70.0
        _, abilities = _parse()
        assert abilities["E"]["total_raw"] == pytest.approx(_E_BONUS_RAW, abs=1e-9)
        assert abilities["E"]["total_raw"] == pytest.approx(169.857142, abs=1e-6)

    def test_per_swing_damage_pricing_is_unchanged_by_the_option(self) -> None:
        """The reset buys swings; it never re-prices one.  With the option
        on (today: ignored; post-contract: the reset declaration) the E
        row's per-cast damage stays 212.45377142857143 = auto hit
        127.5252 + E bonus 84.92857142857143 at 100 armor."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        for result in (off, on):
            row = result["breakdown"]["E"]
            assert row["total_damage"] / row["casts"] == pytest.approx(
                _E_SWING, abs=1e-9
            )

    def test_the_passive_steroid_and_the_amp_are_unchanged_by_the_option(
        self,
    ) -> None:
        """Parse-level: the option leaves the stat_buff and the amped
        total_raw byte-identical (today the key is inert; post-contract
        the payload switch touches only empowers_next_auto)."""
        _, off = _parse(None)
        _, on = _parse({OPTION_KEY: True})
        assert on["E"]["stat_buff"] == off["E"]["stat_buff"]
        assert on["E"]["total_raw"] == off["E"]["total_raw"]
        assert on["E"]["parts"] == off["E"]["parts"]


# ---------------------------------------------------------------------------
# S3 — The option contract (meta, classification, parse effects, parity)
# ---------------------------------------------------------------------------


class TestOptionContract:
    def test_default_parity_absent_vs_false_direct_engine(self) -> None:
        """Option absent vs explicitly False: byte-identical fight on the
        direct engine.  Passes today (the key is inert) and the completed
        contract must keep it — False is the documented default."""
        absent = _fight(None)
        explicit = _fight({OPTION_KEY: False})
        assert _json(absent) == _json(explicit)

    def test_default_parity_absent_vs_false_pipeline(self) -> None:
        """Same parity on the pipeline's registered-fight surface, with
        the current default surface pinned: E 2 casts on the 0.0/6.0
        grid (rank-5 cd 6.0s), 8 ordinary autos riding the augmented
        stream (10 swings - 2 on the E row)."""
        absent = _pipeline_fight(None)
        explicit = _pipeline_fight({OPTION_KEY: False})
        assert _json(absent) == _json(explicit)
        assert absent["breakdown"]["E"]["casts"] == 2
        assert _e_times(absent) == _approx_times([0.0, 6.0])
        assert absent["breakdown"]["auto_attacks"]["count"] == 8

    def test_option_meta_declares_e_reset_throughput(self) -> None:
        """Post-contract: the module declares the bool option (default
        False, label naming the reset) beside the two existing options,
        and the central rotation classification is irrelevant/E — a
        throughput option, not a rotation edge (the q_tumble_reset
        precedent)."""
        meta = get_champion_options_meta(CHAMPION)
        keys = [o["key"] for o in meta["options"]]
        assert keys == [
            "mundo_missing_health_percent",
            "r_nearby_champions",
            OPTION_KEY,
        ]
        option = next(o for o in meta["options"] if o["key"] == OPTION_KEY)
        assert option["type"] == "bool"
        assert option["default"] is False
        assert "reset" in option["label"].lower()
        rotation = get_champion_option_rotation(CHAMPION)
        assert rotation[OPTION_KEY] == {"role": "irrelevant", "slot": "E"}

    def test_parse_level_declaration_when_on(self) -> None:
        """Post-contract: with the option on the E entry's empower
        declaration carries the reset (a dict, still one swing per cast —
        the Alistar rule) so the engine's burst machinery can lift the
        cast cap; the damage fields AND the passive steroid survive
        untouched (the E-specific coexistence pin: unlike Vayne Q, E's
        entry also carries stat_buff — the payload switch must not drop
        it).  The exact marker shape is the coordinator's; the S4
        schedule pins are authoritative."""
        _, on = _parse({OPTION_KEY: True})
        empower = on["E"]["empowers_next_auto"]
        assert isinstance(empower, dict)
        assert _empower_hits(empower) == 1
        assert _empower_burst_attack_speed(empower) > 0  # self-supplying swings
        assert on["E"]["stat_buff"] == {
            "bonus_attack_damage": pytest.approx(_E_AD_BUFF)
        }
        assert on["E"]["total_raw"] == pytest.approx(_E_BONUS_RAW, abs=1e-9)

    def test_junk_option_values_fail_closed_to_the_default(self) -> None:
        """The module's option read is STRICT (the Vayne ``is True``
        rule): junk values (strings, numbers, None) must leave the fight
        byte-identical to the absent default.  Passes today (the key is
        inert); the completed parse must keep it — a truthy-but-not-bool
        value must never silently switch the reset on."""
        absent = _fight(None)
        for junk in ("yes", 1, 1.0, None):
            assert _json(_fight({OPTION_KEY: junk})) == _json(absent), junk

    def test_assumptions_replace_the_not_modeled_line(self) -> None:
        """Post-contract: the stale "which is not modeled as extra
        attacks" assumption is replaced by a line documenting the
        e_reset_throughput option (the w_kill_assertion precedent)."""
        meta = get_champion_options_meta(CHAMPION)
        assert not any(
            "not modeled as extra attacks" in text for text in meta["assumptions"]
        )
        assert any(OPTION_KEY in text for text in meta["assumptions"])


# ---------------------------------------------------------------------------
# S4 — Opted-in reset schedule (Model A: extra autos)
# ---------------------------------------------------------------------------
# MODEL A PINNED HERE: the ordinary auto stream is untouched and every
# accepted E cast buys one extra swing.  Reference fight (AS 1.0, 10s,
# 100% uptime): 10 ordinary autos; E's cooldown-limited schedule is 2
# casts (0.25 and 6.25 — rank-5 cd 6.0s; the next cast would start at
# 12.25, after the 10s window).  Unlike Vayne Q (cd 2/3s, 16 casts, cap
# 12), E's ambient-auto cap (10) does NOT bind in this window — the
# schedule is identical on and off; the observable delta is the two
# bought swings: auto row 8 -> 10, total swings 10 -> 12.  If the
# coordinator picks a longer reference window or a shorter effective cd
# (haste), these counts are the pins to reconcile — flagged in the
# section header for the coordinator.


class TestOptedInResetSchedule:
    def test_e_casts_stay_on_the_cooldown_grid(self) -> None:
        """The E casts ride the exact cooldown grid on AND off the option
        (2 casts: 0.25, 6.25 — the schedule is cooldown-bound at rank-5
        cd 6.0s, so the ambient-auto cap never binds in this window and
        the reset cannot move the cast times; the cast_timeline display
        rounds times to 3 decimals (damage.py), the schedule itself is
        the exact grid).  Passes today (the key is inert) and must stay
        identical once the opted-in schedule lands — the observable
        delta of the reset is the bought swings (the S4 xfails below),
        never a moved cast grid."""
        off = _fight(None)
        result = _fight({OPTION_KEY: True})
        assert result["breakdown"]["E"]["casts"] == 2
        assert _e_times(result) == _approx_times(_E_CAST_TIMES)
        assert _e_times(result) == _e_times(off)

    def test_each_cast_buys_one_extra_swing(self) -> None:
        """Total swings = 10 ordinary autos + 2 reset swings = 12: the
        auto row carries the 10 ordinary autos (was 8 — two swings move
        off it only in the sense that the bought swings are added) and
        the E row keeps its 2 empowered swings (reattribution)."""
        result = _fight({OPTION_KEY: True})
        assert result["breakdown"]["auto_attacks"]["count"] == _ON_AUTOS
        assert result["breakdown"]["E"]["casts"] == 2
        assert (
            result["breakdown"]["auto_attacks"]["count"]
            + result["breakdown"]["E"]["casts"]
        ) == 12

    def test_damage_delta_from_the_reference_fight(self) -> None:
        """E row 2 x 212.45377142857143 = 424.9075428571429 (UNCHANGED);
        auto row 10 x 127.5252 = 1275.252 (was 8 x 127.5252 = 1020.2016);
        Q 926.1 / W 230.0 / R 0 unchanged; total 2856.259542857143 vs
        2601.209142857143 off (+255.0504 = 2 x 127.5252)."""
        on = _fight({OPTION_KEY: True})
        off = _fight(None)
        assert on["breakdown"]["E"]["total_damage"] == pytest.approx(
            2 * _E_SWING, abs=1e-6
        )
        assert on["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            _ON_AUTOS * _AUTO_HIT, abs=1e-6
        )
        assert off["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            _OFF_AUTOS * _AUTO_HIT, abs=1e-6
        )
        assert on["breakdown"]["Q"]["total_damage"] == pytest.approx(
            off["breakdown"]["Q"]["total_damage"], abs=1e-9
        )
        assert on["breakdown"]["W"]["total_damage"] == pytest.approx(
            off["breakdown"]["W"]["total_damage"], abs=1e-9
        )
        assert off["total_damage"] == pytest.approx(_OFF_TOTAL, abs=1e-6)
        assert on["total_damage"] == pytest.approx(_ON_TOTAL, abs=1e-6)
        assert on["total_damage"] - off["total_damage"] == pytest.approx(
            2 * _AUTO_HIT, abs=1e-6
        )


# ---------------------------------------------------------------------------
# S5 — One-rotation + zero-auto interplay
# ---------------------------------------------------------------------------


class TestOneRotationAndZeroAuto:
    def test_zero_uptime_forced_swings_unchanged_with_the_option(self) -> None:
        """No auto stream -> no reset effect: with zero AA uptime the
        option leaves the fight byte-identical — each E cast still forces
        its own swing on the cooldown-limited schedule (2 casts at
        0.25/6.25, the row "attack + bonus") and no ordinary auto row
        exists."""
        off = _fight(None, auto_attack_uptime=0.0)
        on = _fight({OPTION_KEY: True}, auto_attack_uptime=0.0)
        assert _json(off) == _json(on)
        assert on["breakdown"]["E"]["casts"] == 2
        assert on["breakdown"]["E"]["total_damage"] == pytest.approx(
            2 * _E_SWING, abs=1e-6
        )
        assert on["total_damage"] == pytest.approx(_ZERO_UPTIME_TOTAL, abs=1e-6)
        assert on["breakdown"]["auto_attacks"]["count"] == 0

    def test_one_rotation_without_auto_stream_unchanged_with_the_option(
        self,
    ) -> None:
        """One-rotation mode without an auto stream: the single E cast
        carries its own swing and the option changes nothing (byte-
        identical on/off)."""
        off = _fight(None, one_rotation=True, auto_attack_uptime=0.0)
        on = _fight({OPTION_KEY: True}, one_rotation=True, auto_attack_uptime=0.0)
        assert _json(off) == _json(on)
        assert on["breakdown"]["E"]["casts"] == 1
        assert on["breakdown"]["E"]["total_damage"] == pytest.approx(_E_SWING, abs=1e-9)

    def test_one_rotation_with_auto_stream_buys_one_extra_swing(self) -> None:
        """Model A pin (flagged for the coordinator): one-rotation WITH an
        auto stream (10 ambient autos) — the single accepted E cast is a
        reset, so it buys one extra swing: auto row 10 (was 9), E 1,
        total 11 swings.  If the coordinator keeps one-rotation mode
        byte-identical instead, this pin is the one to reconcile."""
        on = _fight({OPTION_KEY: True}, one_rotation=True)
        off = _fight(None, one_rotation=True)
        assert off["breakdown"]["auto_attacks"]["count"] == 9
        assert on["breakdown"]["E"]["casts"] == 1
        assert on["breakdown"]["auto_attacks"]["count"] == 10
        assert off["total_damage"] == pytest.approx(_ONE_ROT_OFF_TOTAL, abs=1e-6)
        assert on["total_damage"] == pytest.approx(_ONE_ROT_ON_TOTAL, abs=1e-6)


# ---------------------------------------------------------------------------
# S6 — Score/receipt parity (full vs score_only)
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_default_surface_is_byte_identical_under_score_only(self) -> None:
        """The scored surfaces are byte-identical full vs score_only
        today: breakdown, total_damage, resource ledger, spends."""
        full = _fight(None)
        score = _fight(None, score_only=True)
        assert _json(full["breakdown"]) == _json(score["breakdown"])
        assert full["total_damage"] == score["total_damage"]
        assert full["resource_spent"] == score["resource_spent"]
        assert full["resource_remaining"] == score["resource_remaining"]
        assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])

    def test_opted_in_surface_stays_byte_identical_under_score_only(self) -> None:
        """With the option on, full vs score_only must stay byte-identical
        on the scored surfaces — passes today (the option is inert) and
        becomes non-vacuous once the opted-in schedule lands (S4)."""
        full = _fight({OPTION_KEY: True})
        score = _fight({OPTION_KEY: True}, score_only=True)
        assert _json(full["breakdown"]) == _json(score["breakdown"])
        assert full["total_damage"] == score["total_damage"]
        assert full["resource_spent"] == score["resource_spent"]
        assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])


# ---------------------------------------------------------------------------
# S7 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_q_w_r_rows_unchanged_by_the_option(self) -> None:
        """The reset touches only the E/auto coupling: Q, W and R
        breakdown rows are byte-identical with the option on or off."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        assert _json(on["breakdown"]["Q"]) == _json(off["breakdown"]["Q"])
        assert _json(on["breakdown"]["W"]) == _json(off["breakdown"]["W"])
        assert _json(on["breakdown"]["R"]) == _json(off["breakdown"]["R"])

    def test_w_charge_ticks_and_detonation_are_unchanged(self) -> None:
        """The 12-tick charge + automatic detonation row (230.0 at 100 MR,
        1 cast) is untouched — the reset changes how many swings exist,
        not the W packet's timings."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        for result in (off, on):
            w = result["breakdown"]["W"]
            assert w["casts"] == 1
            assert w["total_damage"] == pytest.approx(230.0, abs=1e-9)

    def test_missing_health_amp_is_unchanged_at_30_and_70_percent(self) -> None:
        """The amp is orthogonal to the reset: parse-level total_raw at
        30% and 70% missing health is identical with the option on or
        off (and the 70% pin 203.0 survives)."""
        for missing in (30, 70):
            off = _parse({"mundo_missing_health_percent": missing})[1]
            on = _parse(
                {
                    "mundo_missing_health_percent": missing,
                    OPTION_KEY: True,
                }
            )[1]
            assert on["E"]["total_raw"] == off["E"]["total_raw"]
        assert _parse({"mundo_missing_health_percent": 70})[1]["E"][
            "total_raw"
        ] == pytest.approx(203.0, abs=1e-9)

    def test_no_new_control_events(self) -> None:
        """The reset adds no control events: the control surface is empty
        with the option on or off (Mundo has no CC in his damage kit)."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        assert _json(on["control_events"]) == _json(off["control_events"])
        assert on["control_events"] == []

    def test_other_champions_do_not_declare_the_option(self) -> None:
        """The reset option is Dr. Mundo-scoped: no other registered
        champion's option metadata carries the key."""
        for name in registered_champion_names():
            if name == CHAMPION:
                continue
            keys = {o["key"] for o in get_champion_options_meta(name)["options"]}
            assert OPTION_KEY not in keys, name


# ---------------------------------------------------------------------------
# S8 — Fail-closed validation
# ---------------------------------------------------------------------------


class TestFailClosedValidation:
    def test_api_rejects_unknown_option_keys(self) -> None:
        """The public API boundary fails closed on option keys the module
        does not declare — a never-declared typo stays rejected before
        and after the completion."""
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json={
                "champion": CHAMPION,
                "level": _LEVEL,
                "items": [],
                "role": "top",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                "fight_mode": "time_based",
                "fight_duration": 10,
                "include_auto_attacks": True,
                "target_health": 1000,
                "target_armor": 100,
                "target_mr": 100,
                "champion_options": {OPTION_KEY + "_typo": True},
            },
        )
        assert response.status_code == 400
        assert "unknown option" in response.get_json()["error"]

    def test_api_rejects_non_bool_option_values(self) -> None:
        """Once the bool option is declared, the API's existing option
        validator rejects a non-bool value with the typed message (today
        the key is unknown, so the message differs — hence the xfail)."""
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json={
                "champion": CHAMPION,
                "level": _LEVEL,
                "items": [],
                "role": "top",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                "fight_mode": "time_based",
                "fight_duration": 10,
                "include_auto_attacks": True,
                "target_health": 1000,
                "target_armor": 100,
                "target_mr": 100,
                "champion_options": {OPTION_KEY: "yes"},
            },
        )
        assert response.status_code == 400
        assert "must be true or false" in response.get_json()["error"]

    def test_api_accepts_the_option_and_applies_it(self) -> None:
        """Post-contract: the declared bool option is accepted (200) and
        the reset is applied on the API surface (10s, 0.8 uptime default
        -> floor(1.020625 x 10 x 0.8) = 8 ordinary autos + 2 bought
        swings): auto count 6 -> 8, E stays 2 casts.  Today the key is
        unknown (400), hence the xfail."""
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        def call(options: dict) -> dict:
            response = client.post(
                "/api/calculate",
                json={
                    "champion": CHAMPION,
                    "level": _LEVEL,
                    "items": [],
                    "role": "top",
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                    "fight_mode": "time_based",
                    "fight_duration": 10,
                    "include_auto_attacks": True,
                    "target_health": 1000,
                    "target_armor": 100,
                    "target_mr": 100,
                    "champion_options": options,
                },
            )
            assert response.status_code == 200
            return response.get_json()["breakdown"]

        default_body = call({})
        on_body = call({OPTION_KEY: True})
        assert default_body["auto_attacks"]["count"] == 6
        assert on_body["auto_attacks"]["count"] == 8
        assert on_body["E"]["casts"] == 2
        assert default_body["E"]["total_damage"] == pytest.approx(
            on_body["E"]["total_damage"], abs=0.05
        )
        assert on_body["Q"]["casts"] == 3
        assert on_body["W"]["casts"] == 1


# ---------------------------------------------------------------------------
# S9 — Regression surface (run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity set with
# ``.venv/bin/python -m pytest``:
#
#   tests/test_mundo_e_reset.py              (this file)
#   tests/test_dr_mundo.py                   (existing Dr. Mundo surface)
#   tests/test_vayne_q_reset.py              (the reset-throughput template)
#   tests/test_vayne.py
#   tests/test_darius_w_kill_refund.py       (the kill-assertion pattern)
#   tests/test_darius.py
#   tests/test_mana_restore_refund.py
#   tests/test_ezreal_w_mark_refund.py
#   tests/test_jayce_w_mana_restore.py
#   tests/test_jayce.py
#   tests/test_resource_ledger.py
#   tests/test_resource_ledger_consumers.py
#   tests/test_resource_ledger_champion_consumers.py
#   tests/test_catalyst_resource_ledger.py
#   tests/test_item_sustain.py
#   tests/test_champion_options.py
#   tests/test_app.py
