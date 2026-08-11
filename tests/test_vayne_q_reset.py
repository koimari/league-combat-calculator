"""P4 Vayne Q (Tumble) — attack-reset throughput / reset acceleration
(test-matrix owner: RLM-2 C).

Focused TDD matrix for the sourced attack-reset throughput contract.
CURRENT RUNTIME FACTS (verify-before-pin completed against
``src/calculator/champions/vayne.py``, ``src/calculator/damage.py``,
``data/champions.json`` and ``data/atoms/abilities.json``):

- ``vayne.py`` ships ``_tumble`` (the empowered-auto entry — Bonus
  Physical Damage 75/85/95/105/115 %AD + 50 %AP at ranks 1-5, stamped
  ``empowers_next_auto`` so casts are capped at the auto count) whose
  cooldown couples to R's published ``tumble_cd_reduction_percent``
  (R rank 3 halves it: 2.0 -> 1.0; the module ASSUMPTIONS record "the
  dash is an attack reset, so it costs no attack time (reset
  acceleration not modeled)").
- ``damage._resolve_cast_plan`` caps empowered-auto casts at the auto
  count: the casts are "spent in attack-cooldown dead time (the
  in-game reset acceleration is not modeled — conservative)".  With no
  auto stream at all each cast forces its own swing (the zero-uptime
  rule).  ``_apply_empowered_burst_autos`` re-times the auto stream
  around bursts that declare their own ``attack_speed`` (Jayce's Hyper
  Charge) — the existing machinery that BUYS extra autos.
- The cached Q data carries the empower prose with the 3s window
  (``effects[0]``) and the reset prose (``effects[1]``: "Tumble resets
  Vayne's basic attack timer.") with NO leveling — so, like Darius W's
  kill rule, the reset has no atom.  Cost is flat 30, cooldown
  6/5/4/3/2 (affectedByCdr); the four Q atoms are the AD-modifier, the
  AP-modifier, ``timing.active_duration`` (3s window) and
  ``timing.cooldown``.
- The reset's through-put (the extra autos the reset buys) is NOT
  modeled: Q casts never exceed the ambient auto count and the auto
  count is untouched.

The P4-Vayne-Q coordinator's completion adds the SMALLEST opt-in
contract for that throughput: a ``q_tumble_reset`` bool option
(default False) that, when on, treats each accepted Q cast as an
attack reset — the empowered swing fires immediately (zero dead time)
and BUYS one extra swing on top of the ambient auto stream, lifting
the cast cap to the cooldown-limited schedule.  Default fights and
every registered fight stay byte-identical when the option is absent
or False.  Genuinely absent mechanics are ``xfail`` with reason
"awaiting P4-Vayne-Q wiring"; the completion removes the markers and
reconciles any pin it disagrees with.

CONTRACT SEMANTICS PINNED HERE (Model A — extra autos): the ordinary
auto stream is untouched (floor(AS x duration x uptime)) and every
accepted Q cast adds one reset swing; total swings = ordinary autos +
Q casts.  The alternative "re-timed swings" model (each reset swing
replaces/advances the next ordinary auto) is flagged to the
coordinator in the section comments — the pins below are Model A.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + atoms + module declaration: the cached Q
      effects verbatim (the 3s-window empower prose + the reset prose),
      Bonus Physical Damage 75/85/95/105/115 %AD + 50 %AP, cost 30,
      cd 6/5/4/3/2 (affectedByCdr), the four Q atoms (id + hash), the
      reset-atom ABSENCE, the module's ``_tumble`` / OPTIONS /
      ASSUMPTIONS declaration.
  S2  Empowered-auto baseline (unchanged by the reset contract): the
      bonus 354.75 at the reference build, one empowered attack per
      cast, the 3s window, the R coupling cooldown, the per-swing
      damage pricing on and off the option.
  S3  The option contract: the ``q_tumble_reset`` option (meta +
      central rotation classification), the parse-level declaration
      when on (the entry fields), the damage surface untouched, the
      fail-closed API validation, absent-vs-False default parity on
      the direct engine AND the pipeline registered-fight surface.
  S4  Opted-in reset schedule (Model A): with the option on the Q
      casts lift to the cooldown-limited grid, each cast buys one
      extra swing, the W proc count and the damage delta from the
      reference fight — exact times/counts/damage pinned.
  S5  One-rotation + zero-auto interplay: no auto stream -> no reset
      effect (the forced-swing rule unchanged, byte-identical with the
      option on); one-rotation with an auto stream -> the single cast
      buys one extra swing (Model A pin, flagged for the coordinator).
  S6  Score/receipt parity: the scored surface is byte-identical full
      vs score_only today and must stay so on the opted-in schedule.
  S7  Unchanged boundaries: Q damage pricing, W procs, E/R, the R
      coupling, other champions, control events.
  S8  Fail-closed: the API boundary rejects unknown keys today and
      non-bool values once the option is declared; the option never
      silently no-ops when on (S4 pins).
  S9  Regression surface: ``tests/test_vayne.py`` stays green plus the
      mandated sanity set (run list in the module footer).

Expected values are recomputed from ``data/champions.json`` rows, the
live atomization and the module's own typed extractor — no literal
damage constants beyond the sourced cost 30, the sourced cooldown
grid and the reference build's own stats.
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
from src.calculator.champions import vayne as vayne_module
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

CHAMPION = "Vayne"
# The P4-Vayne-Q coordinator wires the opt-in reset contract; genuinely
# absent mechanics are xfailed with this reason.
_AWAIT = "awaiting P4-Vayne-Q wiring"

# The contract option key (the "smallest opt-in" reset-acceleration
# control; the coordinator's completion declares it).
OPTION_KEY = "q_tumble_reset"

# Sourced Q values (cached rows, pinned in S1).
Q_COST = 30.0
Q_COOLDOWNS = [6.0, 5.0, 4.0, 3.0, 2.0]
# The four cached Q atoms (data/atoms/abilities.json + live atomization).
Q_ATOMS = {
    "bonus_ad": (
        "ability.bonus _physical _damage.modifier_0",
        "431e1de1196a0035",
        [75.0, 85.0, 95.0, 105.0, 115.0],
    ),
    "bonus_ap": (
        "ability.bonus _physical _damage.modifier_1",
        "b0b88edb9077bd18",
        [50.0] * 5,
    ),
    "active_duration": ("timing.active_duration", "568a84f9430078e3", [3.0]),
    "cooldown": ("timing.cooldown", "c9023255a08ea0bc", Q_COOLDOWNS),
}

# Reference build (test_vayne.py's TestTumbleAutoCoupling setup): level
# 18, Q5/W5/E5/R3, +100 bonus AD, +100 AP, 50 ability haste, 1.29 AS.
_LEVEL = 18
_BONUS_AD = 100.0
_AP = 100.0
_HAS = 50.0
_AS = 1.29
_DURATION = 10.0
# R rank 3 halves Q's cooldown (2.0 -> 1.0); 50 haste -> 1.0 * 100/150
# = 2/3 exactly, so the cooldown grid is k * 2/3.
_Q_CD = 2.0 * (1.0 - 0.5) * 100.0 / (100.0 + _HAS)  # == 2/3
_Q_GRID = [k * _Q_CD for k in range(16)]  # 0 .. 10.0 inclusive (16 casts)
# Engine AD = 200 total AD (incl. the 100 bonus) + 65 R buff = 265.
_ENGINE_AD = 200.0 + 65.0
# Q bonus at the reference build: 1.15 * 265 + 0.5 * 100.
_Q_BONUS = 1.15 * _ENGINE_AD + 0.5 * _AP  # 354.75
# Auto per-hit after 100 armor; Q per-swing = auto hit + Q bonus.
_AUTO_HIT = _ENGINE_AD * 100.0 / 200.0  # 132.5
_Q_SWING = _AUTO_HIT + _Q_BONUS * 100.0 / 200.0  # 309.875
_W_PROC = 200.0  # max(2000 * 0.10, 110) at the reference target


def _stats() -> dict:
    """The reference build's explicit stat packet (direct engine)."""
    return {
        "level": float(_LEVEL),
        "attack_damage": 200.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": _BONUS_AD,
        "ability_power": _AP,
        "attack_speed": _AS,
        "attack_speed_ratio": 0.658,
        "critical_strike_chance": 0.0,
        "ability_haste": _HAS,
        "basic_ability_haste": 0.0,
        "ultimate_ability_haste": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "is_melee": False,
        "max_mana": 500.0,
        "resource_regen_per_second": 10.0,
    }


def _parse(options: dict | None = None) -> tuple[dict, dict]:
    """Parse the reference build; the R stat buff re-prices Q at parse
    time (the module's BUFF-phase R), so Q's total_raw already carries
    the +65 AD (the 354.75 pin)."""
    stats = _stats()
    abilities = parse_champion_abilities(
        get_champion(CHAMPION),
        _LEVEL,
        _AP,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
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
        "target_health": 1000.0,
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
    """Pipeline fight (real champion stats) for the registered surface."""
    params = dict(
        target_health=1000.0,
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
        copy.deepcopy(get_champion(CHAMPION)),
        _LEVEL,
        [],
        FightParams(**params),
        score_only=score_only,
    )


def _json(result: dict) -> str:
    """Deterministic JSON-ish fingerprint for byte-identity comparisons."""
    return json.dumps(result, sort_keys=True, default=lambda o: f"<{type(o).__name__}>")


def _q_times(result: dict) -> list[float]:
    return [c["time"] for c in result["cast_timeline"] if c["slot"] == "Q"]


def _approx_times(times: list[float]) -> list:
    return [pytest.approx(t, abs=1e-6) for t in times]


# ---------------------------------------------------------------------------
# S1 — Source evidence, atoms, module declaration
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_q_effects_carry_the_empower_and_reset_prose_verbatim(self) -> None:
        """The cached Q data carries the empower prose with the 3-second
        window (effects[0]) and the reset prose (effects[1]) verbatim;
        the reset row has NO leveling (so no atom can exist for it)."""
        q = get_champion(CHAMPION)["abilities"]["Q"][0]
        assert q["effects"][0]["description"] == (
            "Active: Vayne dashes a fixed distance in the target direction, "
            "though not through terrain, and empowers her next basic attack "
            "within 3 seconds to have an uncancellable windup and deal bonus "
            "physical damage."
        )
        assert q["effects"][1]["description"] == (
            "Tumble resets Vayne's basic attack timer."
        )
        assert q["effects"][1]["leveling"] == []  # no leveling -> no atom (S1)

    def test_q_cost_and_cooldown_are_sourced(self) -> None:
        """Cost 30 flat at every rank; cooldown 6/5/4/3/2 flat,
        affected by CDR; MANA, physical, direction-targeting self-cast."""
        q = get_champion(CHAMPION)["abilities"]["Q"][0]
        assert q["cost"]["modifiers"][0]["values"] == [30] * 5
        assert q["cooldown"]["modifiers"][0]["values"] == [6, 5, 4, 3, 2]
        assert q["cooldown"]["affectedByCdr"] is True
        assert q["resource"] == "MANA"
        assert q["damageType"] == "PHYSICAL_DAMAGE"
        assert q["targeting"] == "Direction"
        assert q["affects"] == "Self"

    def test_bonus_physical_damage_leveling_is_75_to_115_percent_ad_plus_50_ap(
        self,
    ) -> None:
        q = get_champion(CHAMPION)["abilities"]["Q"][0]
        leveling = q["effects"][0]["leveling"][0]
        assert leveling["modifiers"][0]["values"] == [75, 85, 95, 105, 115]
        assert leveling["modifiers"][0]["units"] == ["% AD"] * 5
        assert leveling["modifiers"][1]["values"] == [50] * 5
        assert leveling["modifiers"][1]["units"] == ["% AP"] * 5

    def test_q_atom_rows_and_reset_atom_absence(self) -> None:
        """The catalog and the live atomization agree on exactly the four
        Q rows (AD modifier, AP modifier, 3s active duration, cooldown);
        NO atom sources effects[1] (the reset prose) — the reset is a
        typed rule declaration, not a leveling row."""
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        catalog_q = [
            r
            for r in catalog["objects"][CHAMPION]
            if r["source"].startswith(f"{CHAMPION}.Q[")
        ]
        live_q = list(atomize_abilities(CHAMPION, get_champion(CHAMPION))["Q"])
        assert len(catalog_q) == len(live_q) == len(Q_ATOMS) == 4
        for row in catalog_q + live_q:
            assert "effects[1]" not in row["source"], row["source"]
        by_id = {row["atom_id"]: row for row in catalog_q}
        for key, (atom_id, hash_, values) in Q_ATOMS.items():
            assert by_id[atom_id]["hash"] == hash_, key
            assert by_id[atom_id]["values"] == values, key
        live_by_id = {row["atom_id"]: row for row in live_q}
        for atom_id in by_id:
            assert live_by_id[atom_id]["values"] == by_id[atom_id]["values"]

    def test_module_declares_the_tumble_slot(self) -> None:
        """The module's SLOTS map Q to _tumble, the parser is built for
        the exact cached champion name, and the option surface today is
        exactly condemn_wall (the pre-contract declaration)."""
        assert vayne_module.SLOTS["Q"] is vayne_module._tumble
        assert vayne_module.parse_abilities is not None
        assert get_champion(CHAMPION)["name"] == CHAMPION
        meta = get_champion_options_meta(CHAMPION)
        assert "condemn_wall" in [o["key"] for o in meta["options"]]


# ---------------------------------------------------------------------------
# S2 — Empowered-auto baseline (unchanged by the reset contract)
# ---------------------------------------------------------------------------


class TestEmpoweredAutoBaseline:
    def test_q_bonus_empowers_one_attack(self) -> None:
        """Q rank 5 at the reference build: 1.15 x 265 + 0.5 x 100 =
        354.75 bonus physical damage, one empowered attack per cast (the
        Alistar rule), cooldown 1.0 with R rank 3 (the R coupling), cost
        30."""
        _, abilities = _parse()
        q = abilities["Q"]
        assert q["rank"] == 5
        assert q["damage_type"] == "physical"
        assert q["total_raw"] == pytest.approx(_Q_BONUS, abs=1e-9)
        assert q["parts"][0].amount == pytest.approx(_Q_BONUS, abs=1e-9)
        assert q["empowers_next_auto"] is True
        assert _empower_hits(q["empowers_next_auto"]) == 1
        assert q["cooldown"] == pytest.approx(1.0, abs=1e-9)
        assert q["resource_cost"] == pytest.approx(Q_COST)

    def test_the_3s_window_is_sourced_and_atomized(self) -> None:
        q = get_champion(CHAMPION)["abilities"]["Q"][0]
        assert "within 3 seconds" in q["effects"][0]["description"]
        assert Q_ATOMS["active_duration"][2] == [3.0]

    def test_per_swing_damage_pricing_is_unchanged_by_the_option(self) -> None:
        """The reset buys swings; it never re-prices one.  With the option
        on (today: ignored; post-contract: the reset declaration) the Q
        row's per-cast damage stays 309.875 = auto hit 132.5 + Q bonus
        177.375 at 100 armor."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        for result in (off, on):
            row = result["breakdown"]["Q"]
            assert row["total_damage"] / row["casts"] == pytest.approx(
                _Q_SWING, abs=1e-9
            )

    def test_w_per_proc_pricing_is_unchanged_by_the_option(self) -> None:
        """Silver Bolts stays 200 true damage per proc (max(2000*0.10,
        110)) — the reset changes how many swings there are, not what a
        proc is worth."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        for result in (off, on):
            w = result["breakdown"]["on_hit_ability_W"]
            assert w["damage_per_hit"] == pytest.approx(_W_PROC, abs=1e-9)


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
        the current default surface pinned: Q 10 casts on the 0.25..9.25
        grid (R-coupled 1.0s cooldown after E's 0.25 cast), all 10 swings
        empowered, 3 Silver Bolts procs."""
        absent = _pipeline_fight(None)
        explicit = _pipeline_fight({OPTION_KEY: False})
        assert _json(absent) == _json(explicit)
        assert absent["breakdown"]["Q"]["casts"] == 10
        assert _q_times(absent) == _approx_times([0.25 + k for k in range(10)])
        assert absent["breakdown"]["auto_attacks"]["count"] == 0
        assert absent["breakdown"]["on_hit_ability_W"]["count"] == 3

    def test_option_meta_declares_q_tumble_reset(self) -> None:
        """Post-contract: the module declares the bool option (default
        False, label naming the reset) beside condemn_wall, and the
        central rotation classification is irrelevant/Q — a throughput
        option, not a rotation edge (the w_kill_assertion precedent)."""
        meta = get_champion_options_meta(CHAMPION)
        keys = [o["key"] for o in meta["options"]]
        assert keys == ["condemn_wall", OPTION_KEY]
        option = next(o for o in meta["options"] if o["key"] == OPTION_KEY)
        assert option["type"] == "bool"
        assert option["default"] is False
        assert "reset" in option["label"].lower()
        rotation = get_champion_option_rotation(CHAMPION)
        assert rotation[OPTION_KEY] == {"role": "irrelevant", "slot": "Q"}

    def test_parse_level_declaration_when_on(self) -> None:
        """Post-contract: with the option on the Q entry's empower
        declaration carries the reset (a dict, still one swing per cast
        — the Alistar rule) so the engine's burst machinery can lift the
        cast cap; the damage fields themselves are untouched (S2).  The
        exact marker shape is the coordinator's; the S4 schedule pins are
        authoritative."""
        _, on = _parse({OPTION_KEY: True})
        empower = on["Q"]["empowers_next_auto"]
        assert isinstance(empower, dict)
        assert _empower_hits(empower) == 1
        assert _empower_burst_attack_speed(empower) > 0  # self-supplying swings

    def test_assumptions_replace_the_not_modeled_line(self) -> None:
        """Post-contract: the stale "reset acceleration not modeled"
        assumption is replaced by a line documenting the q_tumble_reset
        option (the w_kill_assertion precedent)."""
        meta = get_champion_options_meta(CHAMPION)
        assert not any(
            "reset acceleration not modeled" in text for text in meta["assumptions"]
        )
        assert any(OPTION_KEY in text for text in meta["assumptions"])


# ---------------------------------------------------------------------------
# S4 — Opted-in reset schedule (Model A: extra autos)
# ---------------------------------------------------------------------------
# MODEL A PINNED HERE: the ordinary auto stream is untouched and every
# accepted Q cast buys one extra swing.  Reference fight (AS 1.29, 10s,
# 100% uptime): 12 ordinary autos; Q's cooldown-limited schedule is 16
# casts on the k*2/3 grid INCLUDING t=10.0 (a cast counts when it
# STARTS at/before the duration — the engine's boundary, already live
# in the zero-uptime forced-swing schedule).  Total swings 28 -> 9
# Silver Bolts procs.  If the coordinator chooses the "re-timed swings"
# model instead (each reset swing replaces the next ordinary auto), or
# excludes the t=10.0 boundary cast, these pins are the ones to
# reconcile — flagged in the section header for the coordinator.


class TestOptedInResetSchedule:
    def test_q_casts_lift_to_the_cooldown_grid(self) -> None:
        """With the option on the cast cap lifts: Q casts 16 times on the
        k*2/3 grid (0 .. 10.0 inclusive) instead of the 12 the ambient
        auto count allowed."""
        result = _fight({OPTION_KEY: True})
        assert result["breakdown"]["Q"]["casts"] == 16
        # The cast_timeline display rounds times to 3 decimals
        # (damage.py's round(cast_time, 3)); the schedule itself is the
        # exact k * 2/3 grid.
        assert _q_times(result) == _approx_times([round(t, 3) for t in _Q_GRID])

    def test_each_cast_buys_one_extra_swing(self) -> None:
        """Total swings = 12 ordinary autos + 16 reset swings = 28: the
        auto row keeps 12 (the ordinary stream is untouched) and the Q
        row carries the 16 empowered swings (reattribution)."""
        result = _fight({OPTION_KEY: True})
        assert result["breakdown"]["auto_attacks"]["count"] == 12
        assert result["breakdown"]["Q"]["casts"] == 16
        assert (
            result["breakdown"]["auto_attacks"]["count"]
            + result["breakdown"]["Q"]["casts"]
        ) == 28

    def test_w_proc_count_and_damage_delta(self) -> None:
        """28 swings -> 9 Silver Bolts procs (28 // 3): W goes from
        4 procs / 800 true damage to 9 procs / 1800."""
        on = _fight({OPTION_KEY: True})
        off = _fight(None)
        w_on = on["breakdown"]["on_hit_ability_W"]
        w_off = off["breakdown"]["on_hit_ability_W"]
        assert w_off["count"] == 4
        assert w_on["count"] == 9
        # The W row smears each proc's 200 over its 3-swing cycle (the
        # Vayne-W-style row convention), so the 28th swing carries the
        # first third of the 10th cycle: total = 28 x (200/3) = 1866.67,
        # not count x per_hit.
        assert w_on["total_damage"] == pytest.approx(28 * _W_PROC / 3.0, abs=1e-9)

    def test_damage_delta_from_the_reference_fight(self) -> None:
        """Q row 16 x 309.875 = 4958.0; auto row 12 x 132.5 = 1590.0; W
        28 x (200/3) = 1866.67 (the smeared row, 9 completed procs);
        E 681.25 unchanged; total 9095.92 vs 5199.75 off
        (+3896.17: +1239.5 Q, +1590 autos, +1066.67 W)."""
        on = _fight({OPTION_KEY: True})
        off = _fight(None)
        assert on["breakdown"]["Q"]["total_damage"] == pytest.approx(
            16 * _Q_SWING, abs=1e-6
        )
        assert on["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            12 * _AUTO_HIT, abs=1e-6
        )
        assert on["breakdown"]["on_hit_ability_W"]["total_damage"] == pytest.approx(
            28 * _W_PROC / 3.0, abs=1e-6
        )
        assert on["breakdown"]["E"]["total_damage"] == pytest.approx(
            off["breakdown"]["E"]["total_damage"], abs=1e-9
        )
        assert off["total_damage"] == pytest.approx(5199.75, abs=1e-6)
        assert on["total_damage"] == pytest.approx(
            4958.0 + 1590.0 + 28 * _W_PROC / 3.0 + 681.25, abs=1e-6
        )


# ---------------------------------------------------------------------------
# S5 — One-rotation + zero-auto interplay
# ---------------------------------------------------------------------------


class TestOneRotationAndZeroAuto:
    def test_zero_uptime_forced_swings_unchanged_with_the_option(self) -> None:
        """No auto stream -> no reset effect: with zero AA uptime the
        option leaves the fight byte-identical — each Q cast still forces
        its own swing on the cooldown-limited schedule (16 casts, the
        grid including t=10.0) and no Silver Bolts on-hit row exists."""
        off = _fight(None, auto_attack_uptime=0.0)
        on = _fight({OPTION_KEY: True}, auto_attack_uptime=0.0)
        assert _json(off) == _json(on)
        assert on["breakdown"]["Q"]["casts"] == 16
        assert on["breakdown"]["Q"]["total_damage"] == pytest.approx(
            16 * _Q_SWING, abs=1e-6
        )
        assert "on_hit_ability_W" not in on["breakdown"]
        assert on["breakdown"]["auto_attacks"]["count"] == 0

    def test_one_rotation_without_auto_stream_unchanged_with_the_option(
        self,
    ) -> None:
        """One-rotation mode without an auto stream: the single Q cast
        carries its own swing and the option changes nothing (byte-
        identical on/off)."""
        off = _fight(None, one_rotation=True, auto_attack_uptime=0.0)
        on = _fight({OPTION_KEY: True}, one_rotation=True, auto_attack_uptime=0.0)
        assert _json(off) == _json(on)
        assert on["breakdown"]["Q"]["casts"] == 1
        assert on["breakdown"]["Q"]["total_damage"] == pytest.approx(_Q_SWING, abs=1e-9)

    def test_one_rotation_with_auto_stream_buys_one_extra_swing(self) -> None:
        """Model A pin (flagged for the coordinator): one-rotation WITH an
        auto stream (12 ambient autos) — the single accepted Q cast is a
        reset, so it buys one extra swing: auto row 12 (was 11), Q 1,
        total 13 swings.  If the coordinator keeps one-rotation mode
        byte-identical instead, this pin is the one to reconcile."""
        on = _fight({OPTION_KEY: True}, one_rotation=True)
        off = _fight(None, one_rotation=True)
        assert off["breakdown"]["auto_attacks"]["count"] == 11
        assert on["breakdown"]["Q"]["casts"] == 1
        assert on["breakdown"]["auto_attacks"]["count"] == 12


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
        assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])


# ---------------------------------------------------------------------------
# S7 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_e_and_r_rows_unchanged_by_the_option(self) -> None:
        """The reset touches only the Q/auto coupling: E and R breakdown
        rows are byte-identical with the option on or off."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        assert _json(on["breakdown"]["E"]) == _json(off["breakdown"]["E"])
        assert _json(on["breakdown"]["R"]) == _json(off["breakdown"]["R"])

    def test_r_coupling_survives_the_option(self) -> None:
        """Q's cooldown stays R-coupled (1.0 with R rank 3) when the
        option is on — the reset accelerates the auto stream, not Q's
        cooldown."""
        _, abilities = _parse({OPTION_KEY: True})
        assert abilities["Q"]["cooldown"] == pytest.approx(1.0, abs=1e-9)

    def test_no_new_control_events(self) -> None:
        """The reset adds no control events: the only control source
        stays E's stun, with the option on or off."""
        off = _fight(None)
        on = _fight({OPTION_KEY: True})
        assert _json(on["control_events"]) == _json(off["control_events"])
        assert on["control_events"] == []

    def test_other_champions_do_not_declare_the_option(self) -> None:
        """The reset option is Vayne-scoped: no other registered
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
        the reset is applied — Q's public casts exceed the ambient auto
        cap (10 today on the pipeline surface).  Today the key is
        unknown (400), hence the xfail."""
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
                "champion_options": {OPTION_KEY: True},
            },
        )
        assert response.status_code == 200
        # The API surface (10s, Q CD 1.0s, 8 ambient autos): the cap lifts
        # from 8 to the full cooldown grid (10 casts), the bought swings
        # surface as the auto row (8 ordinary autos), and the W procs ride
        # the augmented stream (6 vs 2).
        body = response.get_json()["breakdown"]
        assert body["Q"]["casts"] == 10
        assert body["auto_attacks"]["count"] == 8
        assert body["on_hit_ability_W"]["count"] == 6


# ---------------------------------------------------------------------------
# S9 — Regression surface (run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity set with
# ``.venv/bin/python -m pytest``:
#
#   tests/test_vayne_q_reset.py              (this file)
#   tests/test_vayne.py                      (existing Vayne surface)
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
