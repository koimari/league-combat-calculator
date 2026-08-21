"""P4/P1 - Aurelion Sol Q "Breath of Light" Stardust scaling (test-matrix owner: RLM-2 C).

Focused TDD matrix for Q's Stardust-scaled beam/burst packet.  CURRENT
RUNTIME FACTS (verify-before-pin completed, all pinned in S1):

- The module (``src/calculator/champions/aurelion_sol.py``) ships
  ``_breath_of_light``: one per-cast Q channel of 3.25 s (26 sourced beam
  ticks at 0.125 s + 3 bursts at each full second), a timed-fight variant
  that channels the whole duration (``fight_duration_seconds`` injected by
  the pipeline; cooldown 999 in timed mode), the sourced 50%-strength
  secondary beam via the parse-level undeclared ``q_secondary_targets``
  option (clamped 0..5), and W's 108-112% flat-beam modifier.  The burst's
  Stardust %maxHP term is a HARDCODED module constant (0.031% of target
  max HP per stack) beside the degraded wiki parse (values [0,...],
  units "(3.1% Stardust)% of target's maximum health"), binary-confirmed
  in the local Community Dragon cache (QMaxHealthTrueDamagePerStack
  0.00031); the E execute display is 5% + 2.6% per 100 stacks
  (BaseExecutionThreshold 5.0 / ExecutionGrowthPerBreakpoint 0.026
  binary-confirmed).
- The typed ``_StardustRule`` (public_receipt: per_stack_burst_maxhp_pct
  0.031, q_burst_maxhp_pct_per_100 3.1, execute base 5.0 + 2.6 per 100,
  stardust_per_q_burst 2.0, bursts_per_q_channel 3, permanent, source =
  wiki rev 3952788 + the local Community Dragon binary 16.15.8024387)
  rides the ``stardust_stacks`` option's state receipt; the 4.47
  additive ``resource_ledger["stardust"]`` documentary ledger is keyed on
  the option KEY being present (absent/empty carry no ledger; damage is
  identical either way - pinned divergence in S2, flagged for the
  coordinator).
- The option is typed int, default 0, declared 0..999.  The API boundary
  rejects out-of-range/non-int/non-number/unknown keys with named 400s;
  the parse path prices an out-of-range seed AS AUTHORED (no module
  clamp - pinned); the 4.47 ledger walk clamps its opening seed to
  0..999.
- Atoms (data/atoms/abilities.json, object "AurelionSol"): the beam
  per-second flat/AP atoms, the burst flat/AP atoms, the Stardust
  HALF-PARSE atom (values [0,0,0,0,0], units carry the prose), the
  secondary per-second atoms, the timing.active_duration (3.25 s "charge")
  atom, and the timing.cooldown (3 s) atom - ids/hashes pinned in S1/S9.
  The rank-5 "160 s" channel (wiki effects[4]) has NO atom (the binary
  says 9999.0 - drift, see AMBIGUITIES).

CONTRACT PINNED HERE (the P4-Asol-Q completion must satisfy;
genuinely-unsupported behavior is a STRICT xfail with reason
"awaiting P4-Asol-Q ..." - the coordinator flips each xfail to a live
test when the seam lands):

- S1  Source evidence: all SIX Q effect descriptions verbatim, the
      leveling rows (beam per-second/per-tick, burst, secondary, the
      4-value total rows), cost/cooldown/targeting, the atoms
      (ids + hashes; the Stardust atom half-parse), the binary DataValues
      (MaxChannelDuration incl. rank-5 9999, BurstAfter 1.0,
      RankDamagePerSecond, APPerSecond, RankBurstDamage, BurstAPRatio,
      QMassStolen 2.0, QMaxHealthTrueDamagePerStack 0.00031,
      MonsterDamageCap 300, AOEModifier 0.5,
      mSpellCooldownOrSealedQueueThreshold 0.25, E execute 5.0/0.026),
      the module declaration (_StardustRule receipt + option state).
- S2  Default + absent parity: parse-level byte-identical for
      absent/empty/zero; fight totals identical; the ledger presence is
      keyed on the option KEY (pinned divergence); the registered golden
      surface (4 builds x levels 11/18, burst + sustained) recomputes
      byte-identical (2-dp) and the golden parse surface is unchanged.
- S3  Typed option + bounds: meta int/default 0/min 0/max 999; the parse
      path does NOT clamp (1000/-5 priced as authored); the ledger walk
      clamps its opening seed to 999; the API rejects with named 400s.
- S4  Stack thresholds + clamping: the E execute display curve at
      0/50/100/200/300/999; the LINEAR Q burst term (1.86/stack per
      channel, 6.2/stack per timed-10 s); the per-100 milestone math
      (3.1k / 5+2.6k / delta 2.6) at the 100 and 1000 crossings; the
      clamp at max.
- S5  Primary + secondary Q damage: beam per-second/per-tick, the burst
      per full second, the sourced 50% secondary beam per target (0/1/2,
      clamp 5), W's flat-beam modifier on primary + secondary only, the
      Stardust term primary-only, and the total at a real fight.
- S6  Zero hits / zero duration: 0 s -> 0 ticks/0 bursts; 0.25 s -> 2
      ticks/0 bursts; the 0.2 s burst-timer note; STRICT xfail: the
      0.25 s-cancel lockout and the rank-5 160 s channel (not modeled).
- S7  Target and structure rules: the "first enemy hit" beam rule, the
      recast/early-end effects, the monster %maxHP cap (300,
      out-of-scope boundary), and the no-structure-target engine (no
      structure text in the cached packet).
- S8  API validation: accepted (200) + applied (Q total_damage, E
      execute detail, stardust ledger opening); unknown keys 400 (incl.
      the deliberately undeclared q_secondary_targets); non-number /
      non-int / out-of-range 400.
- S9  Source + atom receipts: the rule's public_receipt fields, the
      ledger declaration equality, the module SOURCES revision, the atom
      hashes; STRICT xfail: the atom-backed certification of the module
      constants (the completion's "typed atom-backed values" rule).
- S10 Score/receipt parity: full vs score_only byte-identical for
      absent/zero/seeded fights, stardust ledger included.
- S11 Regression surface: the mandated sanity list (footer).

AMBIGUITY NOTES for the coordinator:

1. WHAT THE COMPLETION SHOULD ADD (smallest contract): a typed,
   atom-backed CERTIFICATION of the module's Stardust constant block
   (per-stack 0.031%, execute 5.0 + 2.6/100, +2 per burst) against the
   ability atoms (the Stardust half-parse atom d7b0a266cad8da3f + the
   binary DataValues) - the S9 xfail pins this.  The primary/secondary
   beam split is ALREADY priced (sourced row exactly half at every rank;
   binary AOEModifier 0.5) - certify the split via the atom PAIR
   (primary per-second c61d5c4ae23676fd / secondary per-second
   4817422734efed23) rather than a new option; no new option is needed.
2. REFERENCE CONFIG (S5/S8 pins): rank 5/5/5/3, level 18, 0 AP,
   target_max_health 2000, MR 40.  One-rotation Q raw 641.25 /
   827.25 / 1571.25 at 0/100/500 stacks (mitigated 458.04 / 590.89 /
   1122.32); timed 10 s Q raw 2050.0 / 2670.0 / 5150.0; E execute
   display 5.0% / 7.6% / 18.0%.
3. ABSENT != DEFAULT at the fight-result level (pinned in S2): the
   4.47 stardust ledger + breakdown row + notes appear only when the
   option KEY is present; None/{} carry no stardust surface.  The
   registered golden fights use champion_options=None.  The completion
   must decide whether the declared default (0) should surface the
   documentary ledger (a behavior change vs the golden surface) or keep
   presence-keying (document the divergence).
4. RANK-5 CHANNEL DRIFT: wiki effects[4] says 160 s; the binary
   MaxChannelDuration rank-5 entry is 9999.0 (indices 5/6).  The module
   ASSUMPTION says "up to 160s at rank 5".  A certification must pick a
   root or declare the drift.
5. Q COST DRIFT (patch-day): wiki cost row 8.75..13.75 mana/s vs binary
   ManaCostPerSecond 30..60.  The mana ledger prices the wiki cost; the
   binary disagrees - flag for the patch-update skill.
6. QMassStolen: base DataValues 2.0 (certified, matches
   stardust_per_q_burst) but the {a110bc47} mode override says 4.0; the
   base value is the certified root - note the override exists.
7. E execute display is LINEAR 5 + 2.6 x stacks/100 (one decimal),
   continuous between per-100 multiples (150 -> 8.9%); the per-100
   milestone rows are display-only (mechanical False), never re-price.
"""

import copy
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.champions.aurelion_sol import (
    _E_EXECUTE_BASE_PCT,
    _E_EXECUTE_PCT_PER_100_STARDUST,
    _Q_BURSTS_PER_CHANNEL,
    _Q_BURST_MAXHP_PCT_PER_STARDUST,
    _Q_CHANNEL_SECONDS,
    AURELION_SOL_STARDUST_RULE,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, ONE_ROTATION_DURATION, run_fight

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
# The data-file key differs from the display/dispatcher name (conftest
# documents the same split: "AurelionSol" in the cache, "Aurelion Sol"
# for get_champion / modules).
_ASOL_DATA = _CHAMPION_DATA["AurelionSol"]
_ABILITIES_ATOMS = json.loads(
    Path("data/atoms/abilities.json").read_text(encoding="utf-8")
)["objects"]["AurelionSol"]
_ITEMS = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
_ASOL_BIN_PATH = Path("data/bin/characters/aurelionsol.bin.json")
_ASOL_BIN = (
    json.loads(_ASOL_BIN_PATH.read_text(encoding="utf-8"))
    if _ASOL_BIN_PATH.exists()
    else None
)
_GOLDEN = json.loads(Path("scripts/golden_baseline.json").read_text(encoding="utf-8"))
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_AWAIT = "awaiting P4-Asol-Q ..."
_TARGET_MAX_HP = 2000.0
# One-rotation per-stack Q delta: 3 bursts x 0.031% of 2000 HP.
_PER_STACK_BURST_DELTA = (
    3.0 * (_Q_BURST_MAXHP_PCT_PER_STARDUST / 100.0) * _TARGET_MAX_HP
)
# Timed-10s per-stack Q delta: 10 bursts x 0.031% of 2000 HP.
_PER_STACK_TIMED10_DELTA = (
    10.0 * (_Q_BURST_MAXHP_PCT_PER_STARDUST / 100.0) * _TARGET_MAX_HP
)


def _stats() -> dict:
    return {
        "attack_damage": 100.0,
        "ability_power": 0.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 40.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 300.0,
        "resource_regen_per_second": 0.0,
        "level": _LEVEL,
    }


def _parse(option: dict | None, *, ap: float = 0.0):
    stats = dict(_stats(), ability_power=ap)
    return stats, parse_champion_abilities(
        get_champion("Aurelion Sol"),
        _LEVEL,
        ap,
        ability_ranks=_RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option,
    )


def _fight(
    option: dict | None,
    *,
    duration: float = 10.0,
    score_only: bool = False,
    cast_order: list[str] | None = None,
    one_rotation: bool = False,
    items: list[dict] | None = None,
    auto_attack_uptime: float = 0.0,
    target_health: float = _TARGET_MAX_HP,
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
            cast_order=(cast_order if cast_order is not None else ["Q", "E", "R"]),
        ),
        score_only=score_only,
        champion_options=dict(option) if option else None,
    )


def _api(option: dict):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aurelion Sol",
            "level": _LEVEL,
            "items": [],
            "role": "mid",
            "ability_ranks": _RANKS,
            "fight_mode": "one_rotation",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "target_health": _TARGET_MAX_HP,
            "target_armor": 50,
            "target_mr": 40,
            "champion_options": option,
        },
    )


def _leveling(ability: dict, attribute: str) -> dict:
    """The first leveling row named *attribute* in one ability entry."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"no leveling {attribute!r} in {ability.get('name')}")


def _resolve(ability: dict, attribute: str, index: int, stats: dict) -> float:
    """Recompute one slot value from the cached leveling rows."""
    total = 0.0
    for modifier in _leveling(ability, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(index, len(values) - 1)
        value = float(values[idx])
        unit = str(units[idx]).strip() if idx < len(units) else ""
        if unit in ("", "%"):
            total += value
        elif unit == "% AP":
            total += value / 100.0 * stats["ability_power"]
        elif unit == "% of target's maximum health" or "Stardust" in unit:
            # The degraded burst modifier row (values all 0) - the module
            # prices the Stardust term itself; never resolve it from data.
            continue
        else:
            raise AssertionError(f"unhandled unit {unit!r} in {attribute}")
    return total


def _q_ability() -> dict:
    return _ASOL_DATA["abilities"]["Q"][0]


def _e_ability() -> dict:
    return _ASOL_DATA["abilities"]["E"][0]


def _atom(atom_id: str, name: str | None = None) -> dict:
    """The unique ability-domain atom for (atom_id[, name]).

    Timing atoms repeat across abilities (active_duration/cooldown exist
    for Q, E, R, ...), so callers pass the ability name to disambiguate.
    """
    matches = [
        a
        for a in _ABILITIES_ATOMS
        if a["atom_id"] == atom_id and (name is None or a.get("name") == name)
    ]
    assert len(matches) == 1, f"atom {atom_id!r} name={name!r}: {len(matches)} matches"
    return matches[0]


def _binary_data_values(*, spell: str, name: str) -> list[float]:
    """The DataValues row named *name* under the given spell node.

    Structure-agnostic: the Community Dragon cache file is rewritten by
    the data tooling (nested-character-record or flattened path-keyed
    spell nodes), so the walk locates every DataValues list and picks
    the row whose containing path mentions the spell token.
    """
    if _ASOL_BIN is None:
        pytest.skip("local Aurelion Sol game-file evidence is unavailable")
    hits: list[tuple[str, list[float]]] = []

    def walk(obj, path: str = "") -> None:
        if isinstance(obj, dict):
            rows = obj.get("DataValues")
            if isinstance(rows, list):
                for dv in rows:
                    if isinstance(dv, dict) and dv.get("name") == name:
                        hits.append((path, list(dv.get("values", []))))
            for key, value in obj.items():
                walk(value, f"{path}/{key}")
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                walk(value, f"{path}[{index}]")

    walk(_ASOL_BIN)
    for hit_path, values in hits:
        if spell in hit_path:
            return values
    if hits:
        return hits[0][1]
    raise AssertionError(f"no DataValue {name!r} in {spell}")


def _item(name: str) -> dict:
    for data in _ITEMS.values():
        if data["name"] == name:
            return data
    raise AssertionError(f"item {name!r} not in cache")


def _q_expected(stats: dict, *, stacks: float = 0.0, w_active: bool = False) -> float:
    """One per-cast Q channel recomputed from the cached leveling rows."""
    q = _q_ability()
    beam = _resolve(q, "Magic Damage per Second", _RANKS["Q"] - 1, stats)
    burst = _resolve(q, "Bonus Magic Damage", _RANKS["Q"] - 1, stats)
    if w_active:
        w = _ASOL_DATA["abilities"]["W"][0]
        modifier = _resolve(
            w, "Breath of Light Flat Damage Modifier", _RANKS["W"] - 1, stats
        )
        beam *= modifier / 100.0
    return beam * _Q_CHANNEL_SECONDS + _Q_BURSTS_PER_CHANNEL * (
        burst + (_Q_BURST_MAXHP_PCT_PER_STARDUST * stacks / 100.0) * _TARGET_MAX_HP
    )


# ---------------------------------------------------------------------------
# S1 - Source evidence (six Q effects, leveling rows, atoms, binary, rule)
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_all_six_q_effects_verbatim(self):
        # All six cached Q effect descriptions verbatim - the full packet
        # the module's per-cast model is built from (charge/channel,
        # first-enemy beam, burst + Stardust + monster cap, recast,
        # early end, rank-5 160 s, 0.25 s-cancel lockout).
        descriptions = [fx["description"] for fx in _q_ability()["effects"]]
        assert descriptions == [
            "Active: Aurelion Sol charges for up to 3.25 seconds to exhale "
            "a beam of starfire, during which he can steer the beam in the "
            "target direction. The beam collides with the first enemy hit to "
            "burn them, revealing them and dealing magic damage to them and "
            "surrounding enemies every 0.125 seconds. Secondary targets are "
            "dealt 50% damage.",
            "Against the primary target, the beam will deal a burst of bonus "
            "magic damage for each full second that it burns them, and "
            "additionally generates 2 Stardust if they are a champion. The "
            "damage based on the target's health ratio is capped at 300 "
            "against monsters.",
            "Breath of Light can be recast within the duration, and does so "
            "automatically afterwards.",
            "Recast: Aurelion Sol ends Breath of Light early.",
            "At rank 5, Breath of Light's channel duration is increased to "
            "160 seconds.",
            "If the channel is cancelled within the first 0.25 seconds, "
            "Breath of Light is placed on a 1-second lockout but does not go "
            "on cooldown.",
        ]

    def test_q_leveling_rows_and_cost_cooldown(self):
        # The leveling rows the module reads: beam per-second (45..105 flat
        # + 55% AP), per-tick (exactly 1/8), burst (60..100 flat + 30% AP +
        # the degraded Stardust modifier row), secondary per-second (exactly
        # half the primary row), the 4-value total rows (rank 5 has no
        # practical cap), the per-second mana cost, and the 3 s cooldown.
        q = _q_ability()
        per_second = _leveling(q, "Magic Damage per Second")
        assert per_second["modifiers"][0]["values"] == [45.0, 60.0, 75.0, 90.0, 105.0]
        assert per_second["modifiers"][1]["units"][0] == "% AP"
        per_tick = _leveling(q, "Magic Damage per Tick")
        assert per_tick["modifiers"][0]["values"] == [
            5.625,
            7.5,
            9.375,
            11.25,
            13.125,
        ]
        for rank in range(5):
            assert per_tick["modifiers"][0]["values"][rank] == pytest.approx(
                per_second["modifiers"][0]["values"][rank] / 8.0
            )
        burst = _leveling(q, "Bonus Magic Damage")
        assert burst["modifiers"][0]["values"] == [60.0, 70.0, 80.0, 90.0, 100.0]
        assert burst["modifiers"][1]["values"] == [30.0] * 5
        # The degraded Stardust modifier row: values all 0, units carry the
        # prose - the module hardcodes 0.031% beside it.
        stardust_modifier = burst["modifiers"][2]
        assert stardust_modifier["values"] == [0.0] * 5
        assert (
            stardust_modifier["units"][0]
            == "(3.1% Stardust)% of target's maximum health"
        )
        secondary = _leveling(q, "Secondary Magic Damage per Second")
        assert secondary["modifiers"][0]["values"] == [
            22.5,
            30.0,
            37.5,
            45.0,
            52.5,
        ]
        for rank in range(5):
            assert secondary["modifiers"][0]["values"][rank] == pytest.approx(
                per_second["modifiers"][0]["values"][rank] / 2.0
            )
        # Total-maximum rows carry only 4 values (rank 5 has no cap).
        assert (
            len(_leveling(q, "Total Maximum Magic Damage")["modifiers"][0]["values"])
            == 4
        )
        assert (
            len(
                _leveling(q, "Secondary Target Total Maximum Damage")["modifiers"][0][
                    "values"
                ]
            )
            == 4
        )
        cost = q["cost"]["modifiers"][0]["values"]
        assert cost == [8.75, 10.0, 11.25, 12.5, 13.75]
        cooldown = q["cooldown"]["modifiers"][0]["values"]
        assert cooldown == [3.0] * 5
        assert q["cooldown"]["affectedByCdr"] is True
        assert q["targeting"] == "Direction"
        assert q["affects"] == "Self, Enemies"
        assert q["spellshieldable"] == "special"

    def test_q_atoms_ids_and_hashes(self):
        # The ability-domain atoms for the beam packet: the beam per-second
        # flat/AP atoms, the burst flat/AP atoms, the Stardust HALF-PARSE
        # atom (values zeroed, units carry the prose), the secondary
        # per-second atom, the 3.25 s "charge" (active_duration) atom, and
        # the 3 s cooldown atom.
        pinned = {
            "ability.magic _damage per _second.modifier_0": "c61d5c4ae23676fd",
            "ability.magic _damage per _second.modifier_1": "846ab8aaf0012779",
            "ability.bonus _magic _damage.modifier_0": "c18bafc0fb46e97d",
            "ability.bonus _magic _damage.modifier_1": "30ada11f6fe83233",
            # Stardust half-parse: values [0 x5], units "(3.1% Stardust)%..."
            "ability.bonus _magic _damage.modifier_2": "d7b0a266cad8da3f",
            "ability.secondary _magic _damage per _second.modifier_0": "4817422734efed23",
            "timing.active_duration": "8f1fc76ded61fc28",  # 3.25 s charge
            "timing.cooldown": "6fb2fb8069fd19a6",  # 3 s
        }
        for atom_id, want_hash in pinned.items():
            # Timing atoms repeat per ability; the Q ones are named
            # "Breath of Light".
            atom = _atom(atom_id, name="Breath of Light")
            assert atom["hash"] == want_hash
        stardust_atom = _atom("ability.bonus _magic _damage.modifier_2")
        assert stardust_atom["values"] == [0.0] * 5
        assert stardust_atom["name"] == "Breath of Light"
        assert (
            stardust_atom["units"][0] == "(3.1% Stardust)% of target's maximum health"
        )
        charge = _atom("timing.active_duration", name="Breath of Light")
        assert charge["values"] == [3.25]
        assert charge["units"] == ["s"]
        cooldown = _atom("timing.cooldown", name="Breath of Light")
        assert cooldown["values"] == [3.0] * 5
        # No atom exists for the rank-5 160 s channel (prose-only).
        assert not any("160" in json.dumps(a) for a in _ABILITIES_ATOMS)

    def test_binary_data_values_corroborate_the_packet(self):
        # Community Dragon binary (client 16.15.8024387): the Q DataValues
        # corroborate every module number - channel 3.25 s (rank 5: 9999.0,
        # the wiki says 160 s - drift, see header ambiguity 4), burst every
        # 1.0 s, beam 105/s flat + 55% AP at rank 5, burst 100 + 30% AP,
        # QMassStolen 2.0, QMaxHealthTrueDamagePerStack 0.00031 (=0.031%),
        # MonsterDamageCap 300, AOEModifier 0.5 (the 50% secondary), and the
        # 0.25 s cancel threshold.
        q = _binary_data_values(spell="AurelionSolQAbility", name="MaxChannelDuration")
        assert q[:5] == [3.25] * 5
        assert q[5] == pytest.approx(9999.0)
        assert _binary_data_values(spell="AurelionSolQAbility", name="BurstAfter")[
            0
        ] == pytest.approx(1.0)
        # Binary index i (1..5) is wiki rank i (index 0 is the unleveled
        # rank-0 row): rank 5 sits at index 5.
        assert _binary_data_values(
            spell="AurelionSolQAbility", name="RankDamagePerSecond"
        )[1] == pytest.approx(45.0)
        assert _binary_data_values(
            spell="AurelionSolQAbility", name="RankDamagePerSecond"
        )[5] == pytest.approx(105.0)
        assert _binary_data_values(spell="AurelionSolQAbility", name="APPerSecond")[
            0
        ] == pytest.approx(0.55)
        assert _binary_data_values(spell="AurelionSolQAbility", name="RankBurstDamage")[
            1
        ] == pytest.approx(60.0)
        assert _binary_data_values(spell="AurelionSolQAbility", name="RankBurstDamage")[
            5
        ] == pytest.approx(100.0)
        assert _binary_data_values(spell="AurelionSolQAbility", name="BurstAPRatio")[
            0
        ] == pytest.approx(0.30)
        assert _binary_data_values(spell="AurelionSolQAbility", name="QMassStolen")[
            0
        ] == pytest.approx(2.0)
        assert _binary_data_values(
            spell="AurelionSolQAbility", name="QMaxHealthTrueDamagePerStack"
        )[0] == pytest.approx(0.00031)
        assert _binary_data_values(
            spell="AurelionSolQAbility", name="MonsterDamageCap"
        )[0] == pytest.approx(300.0)
        assert _binary_data_values(spell="AurelionSolQAbility", name="AOEModifier")[
            0
        ] == pytest.approx(0.5)
        assert _binary_data_values(
            spell="AurelionSolQAbility", name="ManaCostPerSecond"
        )[0] == pytest.approx(30.0)
        assert _binary_data_values(
            spell="AurelionSolEAbility", name="BaseExecutionThreshold"
        )[0] == pytest.approx(5.0)
        assert _binary_data_values(
            spell="AurelionSolEAbility", name="ExecutionGrowthPerBreakpoint"
        )[0] == pytest.approx(0.026)
        assert _binary_data_values(spell="AurelionSolRAbility", name="MassStolen")[
            0
        ] == pytest.approx(5.0)

        # The 0.25 s cancel threshold is a mSpell scalar, not a DataValue:
        # locate it structurally.
        def _find_threshold(obj):
            if isinstance(obj, dict):
                if "mSpellCooldownOrSealedQueueThreshold" in obj:
                    return obj["mSpellCooldownOrSealedQueueThreshold"]
                for value in obj.values():
                    found = _find_threshold(value)
                    if found is not None:
                        return found
            elif isinstance(obj, list):
                for value in obj:
                    found = _find_threshold(value)
                    if found is not None:
                        return found
            return None

        if _ASOL_BIN is None:
            pytest.skip("local Aurelion Sol game-file evidence is unavailable")
        assert _find_threshold(_ASOL_BIN) == pytest.approx(0.25)

    def test_rule_declaration_and_option_state_receipt(self):
        # The typed rule's public_receipt rides the option's state receipt:
        # every Stardust number the module prices is disclosed with
        # provenance (wiki rev 3952788 + the local Community Dragon binary).
        meta = get_champion_options_meta("Aurelion Sol")
        option = next(o for o in meta["options"] if o["key"] == "stardust_stacks")
        state = option["state"]
        receipt = AURELION_SOL_STARDUST_RULE.public_receipt()
        assert state == receipt
        assert receipt["per_stack_burst_maxhp_pct"] == pytest.approx(0.031)
        assert receipt["q_burst_maxhp_pct_per_100"] == pytest.approx(3.1)
        assert receipt["execute_base_pct"] == pytest.approx(5.0)
        assert receipt["execute_pct_per_100_stacks"] == pytest.approx(2.6)
        assert receipt["stardust_per_q_burst"] == pytest.approx(2.0)
        assert receipt["bursts_per_q_channel"] == 3
        assert receipt["permanent"] is True
        assert receipt["source"]["revision_id"] == 3952788
        assert "Community Dragon" in receipt["source"]["label"]


# ---------------------------------------------------------------------------
# S2 - Default + absent parity (registered surface unchanged)
# ---------------------------------------------------------------------------


class TestDefaultAbsentParity:
    def test_absent_empty_zero_parse_byte_identical(self):
        # Parse level: no option, an empty option dict, and the declared
        # default (0) produce byte-identical ability packets.
        _, absent = _parse(None)
        _, empty = _parse({})
        _, zero = _parse({"stardust_stacks": 0})
        assert absent == empty == zero
        assert absent["Q"]["total_raw"] == pytest.approx(641.25)

    def test_absent_empty_zero_fight_damage_identical(self):
        # Fight level: totals and every non-stardust surface are identical.
        # The stardust ledger + breakdown row + notes appear ONLY when the
        # option KEY is present (pinned divergence, header ambiguity 3):
        # the 4.47 documentary ledger is presence-keyed.
        absent = _fight(None, one_rotation=True)
        empty = _fight({}, one_rotation=True)
        zero = _fight({"stardust_stacks": 0}, one_rotation=True)
        assert absent["total_damage"] == empty["total_damage"] == zero["total_damage"]
        for key in ("breakdown", "resource_ledger", "cast_timeline", "notes"):
            assert absent[key] == empty[key]
        assert "stardust" not in (absent.get("resource_ledger") or {})
        assert "stardust" not in (empty.get("resource_ledger") or {})
        assert "stardust" in zero.get("resource_ledger", {})
        assert "stardust" not in absent["breakdown"]
        assert "stardust" in zero["breakdown"]

        # Stripping the documentary stardust surface restores byte-parity.
        def strip(result):
            result = copy.deepcopy(result)
            result.get("resource_ledger", {}).pop("stardust", None)
            result["breakdown"].pop("stardust", None)
            result["notes"] = [n for n in result["notes"] if "Stardust" not in n]
            return result

        assert strip(absent) == strip(zero)

    def test_golden_registered_surface_recomputes_byte_identical(self):
        # The registered golden Aurelion Sol fights (4 builds x levels
        # 11/18, burst + sustained) recompute from the current pipeline
        # with champion_options=None exactly as checked in (2-dp) - the
        # absent surface carries NO stardust contribution.
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
        registered = _GOLDEN["registered_champion_fights"]["Aurelion Sol"]
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
                    data = json.loads(json.dumps(_CHAMPION_DATA["AurelionSol"]))
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
                    # Roadmap session 3 (2026-08-20): W is reclassified from
                    # out_of_scope to no_damage and now surfaces its own
                    # zero-valued breakdown row (module_helpers.no_damage) —
                    # W is in DEFAULT_CAST_ORDER, so the row appears here (and
                    # in the re-pinned golden) even though W carries no damage.
                    # Guard the row explicitly: it must never leak real damage
                    # in ANY of the 16 scenarios.  The full totals — W row
                    # included — are then compared byte-identical against the
                    # re-pinned fixture, so nothing is stripped from the pin.
                    assert totals.get("W", 0.0) == 0.0
                    got = {
                        "breakdown_totals": totals,
                        "total_damage": round(float(result["total_damage"]), 2),
                    }
                    assert got == want, f"{level}/{scenario}: {got} != {want}"
                    assert "stardust" not in totals

    def test_golden_parse_surface_unchanged(self):
        # The golden abilities_level_11 parse surface: one per-cast Q
        # channel - 26 beam ticks at 0.125 s + 3 bursts at 1.0 s, the 3 s
        # cooldown, the per-second mana cost - with no stardust part.
        snapshot = _GOLDEN["champion_baselines"]["AurelionSol"]["abilities_level_11"][
            "Q"
        ]
        assert snapshot["total_raw"] == pytest.approx(641.25)
        assert snapshot["cooldown"] == pytest.approx(3.0)
        assert snapshot["resource_cost"] == pytest.approx(13.75)
        assert snapshot["resource_type"] == "MANA"
        assert snapshot["parts"] == [
            "DamagePart(magic, amount=13.125, count=26, hp_scaled=no, "
            "crit_effectiveness=0.0, time_offset=0.125, hit_interval=0.125)",
            "DamagePart(magic, amount=100.0, count=3, hp_scaled=no, "
            "crit_effectiveness=0.0, time_offset=1.0, hit_interval=1.0)",
        ]


# ---------------------------------------------------------------------------
# S3 - Typed option + bounds
# ---------------------------------------------------------------------------


class TestTypedOptionAndBounds:
    def test_option_meta_typed_int_default_0_bounds_0_999(self):
        meta = get_champion_options_meta("Aurelion Sol")
        option = next(o for o in meta["options"] if o["key"] == "stardust_stacks")
        assert option["type"] == "int"
        assert option["default"] == 0
        assert option["min"] == 0
        assert option["max"] == 999
        assert option["label"] == "Stardust stacks"

    def test_parse_path_prices_out_of_range_as_authored(self):
        # Pinned actual: the module reads float(option) directly - no
        # module-level clamp.  1000 stacks price the linear term for 1000
        # (delta 1.86/stack over the 3 bursts); -5 prices a negative term.
        # The 0..999 boundary lives at the API (S8) and in the 4.47 ledger
        # walk's opening seed (S4).
        _, abilities = _parse({"stardust_stacks": 1000})
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _q_expected(_stats(), stacks=1000.0)
        )
        _, abilities = _parse({"stardust_stacks": -5})
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _q_expected(_stats(), stacks=-5.0)
        )
        assert abilities["Q"]["total_raw"] < _q_expected(_stats())

    def test_ledger_opening_seed_clamped_to_declared_max(self):
        # The 4.47 ledger walk clamps its opening seed to 0..999: a
        # 1000-stack seed opens at 999 while the parse still prices 1000.
        # The fight's Q damage is the parse-time price (unclamped); the
        # ledger documents the clamped counter on top (never re-prices).
        result = _fight({"stardust_stacks": 1000}, one_rotation=True)
        account = result["resource_ledger"]["stardust"]
        assert account["opening_current"] == 999
        assert account["base_maximum"] == 999
        assert result["breakdown"]["Q"]["total_raw"] == pytest.approx(
            _q_expected(_stats(), stacks=1000.0)
        )


# ---------------------------------------------------------------------------
# S4 - Stack thresholds + clamping (the execute curve)
# ---------------------------------------------------------------------------


class TestThresholdCurveAndClamping:
    def test_e_execute_display_curve_at_seeds(self):
        # The E execute display is LINEAR in stacks: 5 + 2.6 x stacks/100
        # (one decimal), continuous between per-100 multiples.  HP text
        # prices against the fight's own target_max_health (2000).
        for seed, want_detail in (
            (0, "Executes below 5.0% max HP (100 HP)"),
            (50, "Executes below 6.3% max HP (126 HP)"),
            (100, "Executes below 7.6% max HP (152 HP)"),
            (200, "Executes below 10.2% max HP (204 HP)"),
            (300, "Executes below 12.8% max HP (256 HP)"),
            (999, "Executes below 31.0% max HP (619 HP)"),
        ):
            _, abilities = _parse({"stardust_stacks": seed})
            assert abilities["E"]["detail"] == want_detail

    def test_q_burst_term_linear_per_stack(self):
        # Each stack adds exactly 3 bursts x 0.031% x 2000 HP = 1.86 to
        # the per-cast channel, at every stack count (0/1/2/300/999).
        _, zero = _parse({"stardust_stacks": 0})
        for seed in (1, 2, 300, 999):
            _, abilities = _parse({"stardust_stacks": seed})
            assert abilities["Q"]["total_raw"] == pytest.approx(
                zero["Q"]["total_raw"] + _PER_STACK_BURST_DELTA * seed
            )

    def test_timed_fight_per_stack_delta_scales_with_bursts(self):
        # A timed 10 s fight channels continuously: 10 bursts, so each
        # stack adds 10 x 0.031% x 2000 HP = 6.2.
        _, zero = _parse({"stardust_stacks": 0, "fight_duration_seconds": 10.0})
        assert zero["Q"]["total_raw"] == pytest.approx(2050.0)
        for seed in (100, 500):
            _, abilities = _parse(
                {"stardust_stacks": seed, "fight_duration_seconds": 10.0}
            )
            assert abilities["Q"]["total_raw"] == pytest.approx(
                zero["Q"]["total_raw"] + _PER_STACK_TIMED10_DELTA * seed
            )

    def test_per_100_milestone_math_at_crossings(self):
        # The 4.47 milestone rows document the per-100 display values only
        # (mechanical False): q_burst_maxhp_pct 3.1k,
        # e_execute_threshold_pct 5 + 2.6k, execute_pct_delta 2.6, with
        # stacks_before/after spanning exactly one 100-step.  Seed 95 + 3
        # Q bursts crosses 100; seed 999 + 3 bursts crosses 1000 (the
        # declared max is display-only - the counter may exceed it).
        def crossings(seed):
            account = _fight({"stardust_stacks": seed}, one_rotation=True)[
                "resource_ledger"
            ]["stardust"]
            return account["threshold_transitions"]

        rows = crossings(95)
        assert len(rows) == 1
        row = rows[0]
        assert row["threshold_count"] == 100
        assert row["q_burst_maxhp_pct"] == pytest.approx(3.1)
        assert row["e_execute_threshold_pct"] == pytest.approx(7.6)
        assert row["execute_pct_delta"] == pytest.approx(2.6)
        assert row["mechanical"] is False
        assert row["stacks_before"] == 0
        assert row["stacks_after"] == 100
        rows = crossings(999)
        assert len(rows) == 1
        assert rows[0]["threshold_count"] == 1000
        assert rows[0]["stacks_before"] == 900
        assert rows[0]["stacks_after"] == 1000
        assert rows[0]["q_burst_maxhp_pct"] == pytest.approx(31.0)
        assert rows[0]["e_execute_threshold_pct"] == pytest.approx(31.0)

    def test_e_threshold_math_matches_module_constants(self):
        # The display curve is exactly the module constants: 5.0 base and
        # 2.6 per 100 - no other number enters the execute line.
        for seed in (0, 50, 100, 200, 300, 999):
            want = _E_EXECUTE_BASE_PCT + _E_EXECUTE_PCT_PER_100_STARDUST * (
                seed / 100.0
            )
            _, abilities = _parse({"stardust_stacks": seed})
            assert abilities["E"]["detail"].startswith(
                f"Executes below {want:.1f}% max HP"
            )


# ---------------------------------------------------------------------------
# S5 - Primary and secondary Q damage
# ---------------------------------------------------------------------------


class TestPrimaryAndSecondaryBeam:
    def test_primary_beam_per_second_and_per_tick(self):
        # Rank 5, 0 AP: beam 105/s flat + 55% AP; 26 ticks per 3.25 s
        # channel at 13.125 per 0.125 s tick; the parts carry the sourced
        # tick/burst cadence.
        _, abilities = _parse({"stardust_stacks": 0})
        stats = _stats()
        beam = _resolve(_q_ability(), "Magic Damage per Second", 4, stats)
        assert beam == pytest.approx(105.0)
        per_tick = _resolve(_q_ability(), "Magic Damage per Tick", 4, stats)
        assert per_tick == pytest.approx(105.0 / 8.0)
        parts = abilities["Q"]["parts"]
        assert len(parts) == 2
        assert parts[0].count == 26
        assert parts[0].amount == pytest.approx(13.125)
        assert parts[0].time_offset == pytest.approx(0.125)
        assert parts[0].hit_interval == pytest.approx(0.125)
        assert parts[1].count == 3
        assert parts[1].amount == pytest.approx(100.0)
        assert parts[1].time_offset == pytest.approx(1.0)
        assert abilities["Q"]["cooldown"] == pytest.approx(3.0)

    def test_one_rotation_total_recomputed_from_leveling(self):
        # The full per-cast channel: beam x 3.25 + 3 bursts, Stardust term
        # added per burst; recomputed from the cached leveling rows at
        # every seed, plus the AP term at 200 AP.
        stats = _stats()
        for seed in (0, 100, 500):
            _, abilities = _parse({"stardust_stacks": seed})
            assert abilities["Q"]["total_raw"] == pytest.approx(
                _q_expected(stats, stacks=seed)
            )
        stats_ap = dict(stats, ability_power=200.0)
        _, abilities_ap = _parse({"stardust_stacks": 100}, ap=200.0)
        assert abilities_ap["Q"]["total_raw"] == pytest.approx(
            _q_expected(stats_ap, stacks=100.0)
        )

    def test_timed_fight_total_at_a_real_fight(self):
        # A timed 10 s fight channels Q continuously: 80 beam ticks +
        # 10 bursts, cooldown 999 (never recasts).  0 AP: 1050 + 10 x
        # (100 + 0.031% x 2000 x stacks).
        _, abilities = _parse({"stardust_stacks": 100, "fight_duration_seconds": 10.0})
        assert abilities["Q"]["total_raw"] == pytest.approx(2670.0)
        parts = abilities["Q"]["parts"]
        assert parts[0].count == 80
        assert parts[1].count == 10
        assert abilities["Q"]["cooldown"] == pytest.approx(999.0)
        assert (
            abilities["Q"]["detail"]
            == "80 sourced beam tick(s) at 0.125s intervals; 10 burst(s) "
            "at each full second."
        )

    def test_secondary_beam_sourced_half_strength_per_target(self):
        # Secondary targets take the sourced 50%-strength beam (the row is
        # exactly half the primary at every rank) per target: 1 target
        # adds 52.5/s x 3.25 = 170.625 over the channel; 2 targets add
        # 341.25 (three parts: secondary ticks, primary ticks, bursts).
        # The Stardust bursts stay PRIMARY-ONLY (the secondary total is
        # unchanged by stacks).  Zero targets add no part.
        _, primary = _parse({"stardust_stacks": 0})
        _, one = _parse({"stardust_stacks": 0, "q_secondary_targets": 1})
        assert one["Q"]["total_raw"] == pytest.approx(
            primary["Q"]["total_raw"] + 52.5 * _Q_CHANNEL_SECONDS
        )
        _, two = _parse({"stardust_stacks": 0, "q_secondary_targets": 2})
        assert two["Q"]["total_raw"] == pytest.approx(
            primary["Q"]["total_raw"] + 52.5 * 2.0 * _Q_CHANNEL_SECONDS
        )
        assert len(two["Q"]["parts"]) == 3
        assert (
            "secondary target(s) take the sourced 50%-strength beam "
            "(105/s total, W-modified)" in two["Q"]["detail"]
        )
        _, two_100 = _parse({"stardust_stacks": 100, "q_secondary_targets": 2})
        assert two_100["Q"]["total_raw"] == pytest.approx(
            two["Q"]["total_raw"] + _PER_STACK_BURST_DELTA * 100
        )
        assert len(primary["Q"]["parts"]) == 2

    def test_secondary_target_count_clamped_to_5(self):
        # The parse-level q_secondary_targets control clamps to 0..5 (the
        # key is deliberately NOT declared in OPTIONS - the read-only
        # option-meta test pins the declared set).
        _, five = _parse({"stardust_stacks": 0, "q_secondary_targets": 5})
        _, six = _parse({"stardust_stacks": 0, "q_secondary_targets": 6})
        assert five["Q"]["total_raw"] == six["Q"]["total_raw"]
        meta = get_champion_options_meta("Aurelion Sol")
        assert all(o["key"] != "q_secondary_targets" for o in meta["options"])

    def test_w_modifier_applies_to_primary_and_secondary_beam_only(self):
        # W rank 5 multiplies the beam flat damage by 112% - primary AND
        # secondary (both are non-burst flat damage) - never the burst
        # base/AP/Stardust terms.  Timed 10 s @100 stacks with W + 2
        # secondary targets: 117.6/s x 10 + 117.6/s x 10 + 10 x 162 = 3972.
        _, abilities = _parse(
            {
                "stardust_stacks": 100,
                "w_active": True,
                "q_secondary_targets": 2,
                "fight_duration_seconds": 10.0,
            }
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(3972.0)
        assert "117.6/s total, W-modified" in abilities["Q"]["detail"]
        # Burst term unchanged by W: 10 x 162 = 1620 with or without W.
        _, no_w = _parse({"stardust_stacks": 100, "fight_duration_seconds": 10.0})
        burst_total_no_w = sum(
            p.amount * p.count for p in no_w["Q"]["parts"] if p.time_offset == 1.0
        )
        burst_total_w = sum(
            p.amount * p.count for p in abilities["Q"]["parts"] if p.time_offset == 1.0
        )
        assert burst_total_w == pytest.approx(burst_total_no_w)


# ---------------------------------------------------------------------------
# S6 - Zero hits / zero duration + the unmodeled channel boundaries
# ---------------------------------------------------------------------------


class TestZeroHitsAndUnmodeledBoundaries:
    def test_zero_duration_yields_no_beam_hits(self):
        # fight_duration_seconds=0: zero ticks, zero bursts, Q total 0 -
        # the parts carry count 0 and the detail names the zeroed window.
        _, abilities = _parse({"stardust_stacks": 0, "fight_duration_seconds": 0.0})
        assert abilities["Q"]["total_raw"] == 0.0
        assert [p.count for p in abilities["Q"]["parts"]] == [0, 0]
        assert (
            abilities["Q"]["detail"]
            == "0 sourced beam tick(s) at 0.125s intervals; 0 burst(s) at "
            "each full second."
        )

    def test_sub_lockout_window_is_not_a_channel(self):
        # At or below the 0.25s cancel lockout the channel cannot start:
        # the cast uses the sourced cooldown and produces zero ticks.
        # The pre-existing 2×13.125 assertion was the old unguarded
        # behaviour; the coordinator's P4-Asol-Q guard replaces it.
        _, abilities = _parse({"stardust_stacks": 100, "fight_duration_seconds": 0.125})
        assert abilities["Q"]["total_raw"] == pytest.approx(0.0)
        assert abilities["Q"]["cooldown"] == pytest.approx(3.0)

    def test_burst_timer_note_pinned(self):
        # The wiki notes: the burst triggers after 5 completed 0.2 s
        # intervals of the burn timer - the source of the per-second
        # cadence the module prices (BurstAfter 1.0 in the binary).
        notes = _q_ability().get("notes", "")
        assert "ticks in 0.2 second intervals" in notes
        assert "[ 5 completed intervals ][ 1 full second ]" in notes
        assert "Spell shield will only block the burst damage" in notes

    def test_quarter_second_cancel_lockout_below_minimum_is_not_a_timed_channel(
        self,
    ):
        # The 0.25s cancel lockout (binary
        # mSpellCooldownOrSealedQueueThreshold) means a channel shorter
        # than 0.25s cannot start: the cast uses the sourced cooldown and
        # produces zero beam ticks and zero bursts.
        _, abilities = _parse({"stardust_stacks": 0, "fight_duration_seconds": 0.25})
        # The sourced rank-5 cooldown is 3.0; the key property is that
        # the channel did NOT start (cooldown is not 999.0).
        assert abilities["Q"]["cooldown"] == pytest.approx(3.0)

    def test_rank5_160s_channel_cap_is_applied(self):
        # A rank-5 timed fight caps at the sourced 160s channel duration
        # (wiki effects[4]; binary MaxChannelDuration 9999.0 is unlimited
        # but the wiki's 160s is the practical game cap).
        _, abilities = _parse({"stardust_stacks": 0, "fight_duration_seconds": 200.0})
        assert abilities["Q"]["total_raw"] == pytest.approx(105.0 * 160.0 + 160 * 100.0)


# ---------------------------------------------------------------------------
# S7 - Target and structure rules
# ---------------------------------------------------------------------------


class TestTargetAndStructureRules:
    def test_beam_hits_the_first_enemy(self):
        # The beam "collides with the first enemy hit" - the 1v1 champion
        # model prices exactly one primary target (the fight's target).
        _, abilities = _parse({"stardust_stacks": 0})
        assert abilities["Q"]["damage_type"] == "magic"
        # The packet-level targeting metadata (the parse entry exposes the
        # damage type; the raw cached packet carries the targeting rules).
        assert _q_ability()["targeting"] == "Direction"
        assert _q_ability()["affects"] == "Self, Enemies"

    def test_monster_cap_is_a_documented_out_of_scope_boundary(self):
        # The burst's %maxHP Stardust term is "capped at 300 against
        # monsters" (wiki prose; binary MonsterDamageCap 300.0).  The 1v1
        # champion model has no monster target kind, so the cap is a named
        # boundary, not a modeled number.
        q_prose = " ".join(
            fx.get("description", "") for fx in _q_ability().get("effects", [])
        )
        assert "capped at 300 against monsters" in q_prose
        assert _binary_data_values(
            spell="AurelionSolQAbility", name="MonsterDamageCap"
        )[0] == pytest.approx(300.0)

    def test_no_structure_target_in_the_packet_or_engine(self):
        # No structure text exists anywhere in the cached Aurelion Sol
        # packet, and the engine has no structure-target concept - the
        # beam's first-enemy rule prices the single champion target only.
        packet = json.dumps(_ASOL_DATA)
        assert "structure" not in packet.lower()
        # The burst aggro + spell-shield lines are the named target rules.
        notes = _q_ability().get("notes", "")
        assert "aggro nearby enemy minions" in notes
        assert "Spell shield will only block the burst damage" in notes


# ---------------------------------------------------------------------------
# S8 - API validation
# ---------------------------------------------------------------------------


class TestApiValidation:
    def test_option_accepted_and_applied(self):
        # 200 + applied: the seeded Q total, the E execute detail, and the
        # stardust ledger opening all reflect the option.
        response = _api({"stardust_stacks": 100})
        assert response.status_code == 200
        body = response.get_json()
        # Q total_damage is the mitigated one-rotation price:
        # (641.25 + 186) x 100/140 = 590.89...
        assert body["breakdown"]["Q"]["total_damage"] == pytest.approx(590.89, abs=0.02)
        assert body["breakdown"]["E"]["detail"] == "Executes below 7.6% max HP (152 HP)"
        account = body["resource_ledger"]["stardust"]
        assert account["opening_current"] == 100
        assert account["closing_current"] == 106.0

    def test_zero_and_max_seeds_accepted(self):
        assert _api({"stardust_stacks": 0}).status_code == 200
        assert _api({"stardust_stacks": 999}).status_code == 200

    def test_unknown_keys_rejected_400(self):
        # Unknown option keys fail closed with a named receipt; the
        # deliberately undeclared q_secondary_targets is rejected too (the
        # parse-level control is not an API option).
        response = _api({"stardust_stackz": 5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options contains unknown option stardust_stackz"
        )
        response = _api({"q_secondary_targets": 2})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options contains unknown option q_secondary_targets"
        )

    def test_non_number_rejected_400(self):
        for bad in ("abc", True, None):
            response = _api({"stardust_stacks": bad})
            assert response.status_code == 400
            assert (
                response.get_json()["error"]
                == "champion_options.stardust_stacks must be a number"
            )

    def test_non_integer_rejected_400(self):
        response = _api({"stardust_stacks": 2.5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.stardust_stacks must be an integer"
        )

    def test_out_of_range_rejected_400(self):
        for bad in (1000, -1):
            response = _api({"stardust_stacks": bad})
            assert response.status_code == 400
            assert (
                response.get_json()["error"]
                == "champion_options.stardust_stacks must be between 0 and 999"
            )


# ---------------------------------------------------------------------------
# S9 - Source and atom receipts
# ---------------------------------------------------------------------------


class TestSourceAndAtomReceipts:
    def test_public_receipt_discloses_every_priced_number(self):
        # The typed rule's receipt is the single declaration of the
        # Stardust contract: every number the module prices appears with
        # provenance, and the receipt mirrors the module constants.
        receipt = AURELION_SOL_STARDUST_RULE.public_receipt()
        assert receipt["per_stack_burst_maxhp_pct"] == pytest.approx(
            _Q_BURST_MAXHP_PCT_PER_STARDUST
        )
        assert receipt["q_burst_maxhp_pct_per_100"] == pytest.approx(
            _Q_BURST_MAXHP_PCT_PER_STARDUST * 100.0
        )
        assert receipt["execute_base_pct"] == pytest.approx(_E_EXECUTE_BASE_PCT)
        assert receipt["execute_pct_per_100_stacks"] == pytest.approx(
            _E_EXECUTE_PCT_PER_100_STARDUST
        )
        assert receipt["stardust_per_q_burst"] == pytest.approx(2.0)
        assert receipt["bursts_per_q_channel"] == _Q_BURSTS_PER_CHANNEL
        assert receipt["permanent"] is True
        assert receipt["source"]["url"].endswith("/en-us/Aurelion_Sol")
        assert receipt["source"]["revision_id"] == 3952788
        assert receipt["source"]["revision_timestamp"] == "2025-09-10T01:55:29Z"
        # The receipt cites both roots (wiki + the Community Dragon binary).
        label = receipt["source"]["label"]
        assert "Local League Wiki cache" in label
        assert "Community Dragon" in label
        assert "16.15.8024387" in label

    def test_ledger_declaration_is_the_public_receipt(self):
        # The 4.47 ledger's declaration is exactly the rule's public
        # receipt - one declaration, two homes.
        result = _fight({"stardust_stacks": 0}, one_rotation=True)
        declaration = result["resource_ledger"]["stardust"]["declaration"]
        assert declaration == AURELION_SOL_STARDUST_RULE.public_receipt()

    def test_module_sources_pin_the_wiki_revision(self):
        # The module SOURCES pin the same wiki revision the receipt cites.
        meta = get_champion_options_meta("Aurelion Sol")
        sources = {row["label"]: row for row in meta["sources"]}
        assert sources["Local League Wiki cache"]["revision_id"] == 3952788
        assert sources["Local League Wiki cache"]["url"].endswith("/en-us/Aurelion_Sol")

    def test_atom_hashes_are_stable(self):
        # The beam packet's atoms are stable source evidence (S1): the
        # primary/secondary per-second pair the completion should certify
        # the 50% split against, and the Stardust half-parse atom that
        # documents the module's hardcode.
        assert (
            _atom("ability.magic _damage per _second.modifier_0")["hash"]
            == "c61d5c4ae23676fd"
        )
        assert (
            _atom("ability.secondary _magic _damage per _second.modifier_0")["hash"]
            == "4817422734efed23"
        )
        assert (
            _atom("ability.bonus _magic _damage.modifier_2")["hash"]
            == "d7b0a266cad8da3f"
        )

    def test_atom_backed_certification_of_module_constants(self):
        # The typed rule exposes an atom-backed certification surface
        # (atom ids + hashes for every priced constant) that documents
        # per_stack_burst_maxhp_pct, the execute base, and the execute
        # per-100 step from the atom/binary roots; the hashes are pinned
        # so a patch that changes the roots trips the tests (fail-closed
        # staleness).
        rule = AURELION_SOL_STARDUST_RULE
        assert rule.atom_ids  # typed atom-backed certification surface
        assert rule.atom_ids["per_stack_burst_maxhp_pct"]["atom_id"] == (
            "ability.bonus _magic _damage.modifier_2"
        )
        assert rule.atom_ids["per_stack_burst_maxhp_pct"]["hash"] == (
            "d7b0a266cad8da3f"
        )
        assert rule.certified_constants["execute_base_pct"] == pytest.approx(
            rule.public_receipt()["execute_base_pct"]
        )


# ---------------------------------------------------------------------------
# S10 - Score/receipt parity
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_full_vs_score_only_byte_identical(self):
        # Absent, zero, and seeded fights: the compiled score path is
        # byte-identical to the full walk - breakdown, totals, the
        # stardust ledger, notes, and the shared cast_timeline fields.
        for option in (None, {"stardust_stacks": 0}, {"stardust_stacks": 100}):
            full = _fight(option, one_rotation=True)
            scored = _fight(option, one_rotation=True, score_only=True)
            assert full["breakdown"] == scored["breakdown"]
            assert full["total_damage"] == scored["total_damage"]
            assert full["resource_spent"] == scored["resource_spent"]
            assert full["resource_remaining"] == scored["resource_remaining"]
            assert full["resource_ledger"] == scored["resource_ledger"]
            assert full["notes"] == scored["notes"]
            assert len(full["cast_timeline"]) == len(scored["cast_timeline"])
            shared = ("time", "slot", "name", "ordinal", "resource_cost")
            for full_row, scored_row in zip(
                full["cast_timeline"], scored["cast_timeline"]
            ):
                assert {k: full_row[k] for k in shared} == {
                    k: scored_row[k] for k in shared
                }

    def test_timed_fight_score_parity(self):
        # Timed fights (continuous Q channel) also match under score_only.
        full = _fight({"stardust_stacks": 100}, duration=10.0)
        scored = _fight({"stardust_stacks": 100}, duration=10.0, score_only=True)
        assert full["total_damage"] == scored["total_damage"]
        assert full["resource_ledger"] == scored["resource_ledger"]


# ---------------------------------------------------------------------------
# S11 - Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (contract 11):
#   .venv/bin/python -m pytest tests/test_aurelion_sol_stardust.py \
#     tests/test_aurelion_sol_stardust_ledger.py tests/test_senna_relic_cannon.py \
#     tests/test_senna_souls_ledger.py tests/test_mana_restore_refund.py \
#     tests/test_ezreal_w_mark_refund.py tests/test_jayce_w_mana_restore.py \
#     tests/test_resource_ledger*.py tests/test_catalyst_resource_ledger.py \
#     tests/test_item_sustain.py tests/test_champion_options.py tests/test_app.py
# Aurelion Sol / stardust grep surface (contract 11), run separately:
#   tests/test_aurelion_sol.py tests/test_e2_dot_1.py tests/test_mechanics_packets.py
