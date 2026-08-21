"""P4 — Vladimir E "Tides of Blood" charge-time ramp (test-matrix owner: RLM-2 C).

Focused TDD matrix for the charge-interpolated nova between the sourced
Minimum/Maximum Magic Damage rows, driven by the ``e_charge_fraction``
option (0 = uncharged minimum, 1 = fully charged after 1s of the 1.5s
channel).  CURRENT RUNTIME FACTS (verify-before-pin completed, all
pinned in S1):

- The cached E (data/champions.json "Vladimir" -> abilities.E[0]) has
  FIVE effects: [0] the charge-window prose ("charges for up to 1.5
  seconds ... increases Tides of Blood's damage over the first second of
  the channel" + the 20% channel self-slow) with leveling EMPTY — THE
  DEGRADED CHARGE-TIME ROW (the AGENTS.md known-degraded list: "Vladimir
  E (charge time)"); [1] the Recast with the "Minimum Magic Damage" row
  (flat 30/45/60/75/90 + 1.5% maximum health + 35% AP) and the "Maximum
  Magic Damage" row (flat 60/90/120/150/180 + 6% maximum health + 80%
  AP); [2] the slow ("If Tides of Blood was charged for at least 1
  second, enemies hit are also slowed for 0.5 seconds", row 40/45/50/55/
  60%); [3] the intercept prose (no leveling); [4] the 12% free rule
  ("If Vladimir is below 12% of his maximum health, Tides of Blood will
  not cost any health.").  The cost row carries values [0,0,0,0,0] with
  the prose unit "2% / 4% / 6% / 8% (based on charge time)" — the
  health cost is NOT atomized/typed anywhere.
- The module (src/calculator/champions/vladimir.py, PACKET_SHA256
  03e211424b005b94fe9d0df6d90a10efc1aa4d935e306143b14b0b254bd3532d)
  ships ``_tides_of_blood``: the E slot parser that interpolates EACH of
  the three modifiers independently between its min and max rows by
  ``e_charge_fraction`` (default 1.0 = fully charged == the reviewed
  packet's max-row numbers exactly), prices the "% maximum health" term
  against the champion's OWN maximum health (ctx.stats["health"]), and
  stamps a detail string with the fraction/ramp/channel semantics.  The
  charge-window constants are HARDCODED module floats with a "verify on
  patch updates" comment: ``_E_CHARGE_RAMP_SECONDS = 1.0`` (the ramp —
  wiki prose only, NO atom carries 1.0) and ``_E_CHANNEL_SECONDS = 1.5``
  (atomized: timing.active_duration [1.5], hash 367b90ae9fc5cf38, plus
  the binary channel atom crowd-control-mobility.channel/VladimirE hash
  940d08fba719e658).  The module also ships the R AMP pseudo-slot
  (hemoplague, 10% debuff, default ON) and the E cooldown now reads the
  LIVE cached array 13/11/9/7/5 (not the reviewed packet's fixed 13.0 —
  HANDOVER §4.12 note).
- Atoms: abilities-domain (data/atoms/abilities.json "Vladimir") E rows
  — minimum _magic _damage.modifier_0/1/2 hashes ed0a9a756a254ee9 /
  2241b298f6dcd8d4 / 6c5d374d3795f5a8; maximum _magic _damage.modifier_
  0/1/2 hashes 1e9f85c82f8835bf / b80d1b0a647bec0f /
  0b370081381fdce8; ability.slow 9542f5ef5b374978; timing.active_
  duration 367b90ae9fc5cf38 (1.5s channel); timing.control_duration
  7e729d1075801443 (0.5s slow); timing.cooldown 15cbce498dc12195.
  Champions-domain (data/atoms/champions.json "Vladimir"): the channel/
  slow/aoe/damage-instance E atoms (940d08fba719e658 / 35908e07efaea3a6
  / 580c5d8ca6091984 / 75001ca6bfeeea3e), the recast nuke
  (VladimirTidesofBloodNuke 2493ebc69f194d05), the health-as-resource
  cost atom (VladimirTidesofBloodCost 77fd5d82b6181e37 — NO numbers),
  the stale E heal atom (VladimirTidesofBloodHeal bba17d1afe12f8bd — E
  has no heal in the current patch), and the inherited VladimirEMissile
  trio (2c71947a806b1959 / 31ee70c52c063735 / 2932ed40dff644d1).  NO
  atom carries the 1.0s ramp (the degraded row's only numeric survivor
  is the 1.5s channel in timing.active_duration).
- Runtime behavior (verified): rank 5, AP 100, health 2500,
  r_hemoplague_debuff=False -> E total_raw 162.5 (fraction 0) / 286.25
  (0.5) / 410.0 (1.0); ranks 1-5 max 290/320/350/380/410, min
  102.5/117.5/132.5/147.5/162.5; the parse entry carries NO
  resource_cost (the health cost 2%/4%/6%/8% current health and the 12%
  free rule are UNMODELED — fight resource_spent 0.0, resource_ledger
  null, control_events [] — the slow is also UNMODELED, "utility" per
  the module ASSUMPTION); direct-parse out-of-range fractions CLAMP
  (2.0 -> max row, -1.0 -> min row) while the API 400s them
  ("champion_options.e_charge_fraction must be between 0.0 and 1.0");
  unknown API keys 400 ("champion_options contains unknown option ...");
  non-numeric 400 ("must be a number"); API breakdown E rows use the
  REAL level-18 stats (health 2470, AP 0): 127.05 / 227.625 / 328.2
  (rounded to 1dp in the app layer).

CONTRACT PINNED HERE (the P4-Vladimir-E completion must satisfy;
genuinely-unsupported boundaries are STRICT xfails with reason
"awaiting P4-Vladimir-E ..." — the coordinator flips each xfail to a
live test when the seam lands):

- S1  Source evidence: all five E effects verbatim, the leveling rows
      (min/max/slow), the cost row + cooldown row, the degraded
      charge-time row (leveling EMPTY), the atoms (ids + hashes,
      abilities + champions domains), the module declaration (constants,
      PACKET_SHA256, SLOTS incl. the hemoplague pseudo-slot,
      MODULE_COVERAGE, OPTIONS/ASSUMPTIONS/SOURCES meta), the reviewed
      packet's max-row E slot the module overrides.
- S2  Charge fractions: E damage at fraction 0/0.25/0.5/1.0 (the
      per-modifier interpolation — flat x2, %maxHP x4, %AP ~x2.3, so
      each modifier interpolates on its own), the min/max endpoints, the
      detail strings, and the health cost at each fraction (UNPRICED
      today: no resource_cost anywhere — live guard + strict xfail for
      the typed cost seam).
- S3  Level endpoints: min/max rows at ranks 1-5 (raw rows + parsed
      totals), the live cooldown array 13/11/9/7/5, rank-0 absence.
- S4  The charge window: 1.5s channel (the sourced atom
      timing.active_duration) vs the 1s ramp (degraded row — prose
      only, no atom, HARDCODED module constant); the detail string's
      semantics (fraction x 1s ramp inside the 1.5s channel); the slow's
      "at least 1 second" boundary == ramp completion.
- S5  Health cost + the 12% free rule: the effect + the notes verbatim;
      today the cost is not modeled anywhere (live guard); STRICT xfail
      for the typed cost seam honoring 2% -> 8% current health by charge
      and the 12% free boundary.
- S6  The slow: the effect + the 40/45/50/55/60% row + the 0.5s control
      duration verbatim; today no slow surface exists (control_events
      [], no cc on the E part — live guard); STRICT xfail for the slow
      seam emitting the rank value for 0.5s ONLY at fraction 1.0 (the
      "charged for at least 1 second" boundary) and nothing below.
- S7  Malformed/stale declarations: the degraded row is never read (the
      fraction IS the selection); the min/max rows resolve by exact
      attribute name (a missing attribute would resolve 0.0 — the
      engine convention; the rows are pinned so drift trips loudly);
      direct-parse clamps vs API 400s (option bounds min 0.0 / max 1.0
      / step 0.1 / default 1.0 / type float); non-numeric raises.
- S8  Source + atom receipts: the hashes, the manifest receipts
      (abilities domain 56c47afaf5f0b20b; champions domain
      49e1c1ddcb91244a; data/champions.json@sha256:afea81a9976904c1),
      the packet-spec digest == PACKET_SHA256, the module SOURCES
      revisions, docs/receipts/champions/vladimir.json (36 atoms);
      STRICT xfail for the typed atom-backed certification of the charge
      model (ramp/channel constants + min/max atom ids in one public
      receipt).
- S9  API validation: the option accepted (200) and applied (E row
      total_damage rises 127.05 -> 227.625 -> 328.2 at level 18, MR 0,
      debuff off); unknown keys 400 with a named receipt; out-of-range
      (1.5 / -0.5) 400; non-numeric 400; inclusive 0.0/1.0 accepted;
      the hemoplague default scales E by exactly 1.1 on top of the
      charge interpolation.
- S10 Score/receipt parity: full vs score_only byte-identical on the
      scored surface (breakdown / total_damage / resource_spent /
      resource_remaining / resource_ledger / notes / cast_timeline
      shared keys) at fractions 0/0.5/1.0, one-rotation and timed.
- S11 Regression surface: the tests/ grep set for "vladimir" is pinned
      to exactly the 11 pre-existing files + this one (growing the set
      requires updating this pin); module meta pins; the mandated sanity
      list (footer).

AMBIGUITY NOTES for the coordinator:

1. CHARGE-MODEL CERTIFICATION vs TYPED SEAM.  The model today is a slot
   parser function plus two HARDCODED module floats (ramp 1.0, channel
   1.5) with a "verify on patch updates" comment.  The 1.5s channel is
   atom-backed (timing.active_duration 367b90ae9fc5cf38); the 1.0s ramp
   exists ONLY in wiki prose (the degraded effects[0] row has no
   leveling — the atomizer extracted nothing for the ramp).  The
   completion should either (a) certify the existing constants with a
   typed public receipt (mirroring the repo's typed-rule-with-public-
   receipt pattern) naming the min/max atom ids + the wiki-prose root
   for the 1s ramp, or (b) add a typed seam carrying the window.
   S8's xfail asserts the receipt surface, not a specific class name.
2. THE 1S RAMP HAS NO ATOM.  Any "atom-backed" certification of the
   ramp value must name the wiki prose (effects[0].description "over
   the first second of the channel" / effects[1].description "increased
   based on charge time up to the first second") as the root — the
   binary/atom catalogs carry no 1.0 ramp value.  The fraction option
   maps linearly onto the ramp: fraction == fraction-seconds of ramp
   (the detail string pins this).
3. HEALTH COST TIER MAPPING IS UNKNOWN.  The cost row's unit prose is
   "2% / 4% / 6% / 8% (based on charge time)" — four discrete tiers but
   NO sourced boundary between them (the wiki gives no charge-time
   thresholds; the in-game cost is per the game scripts).  S2/S5 xfails
   pin ONLY the endpoints (2% at fraction 0, 8% at fraction 1.0,
   monotone between) and the 12% free boundary (effects[4] + the notes'
   per-tick semantics: "verified for every tick of health cost, i.e if
   the first tick drops him below it, the next ones will stop affecting
   him").  The engine also has NO attacker current-health input today —
   a cost seam needs one (or must pin the fraction as the only lever).
4. THE 20% CHANNEL SELF-SLOW IS A SEPARATE BOUNDARY.  effects[0]
   prose: Vladimir "becomes slowed by 20% afterwards for the remaining
   duration" (after 1s of charging).  This is a SELF slow, distinct
   from the enemy slow in effects[2]; neither is modeled.  The S6 xfail
   covers the ENEMY slow; the self-slow is utility — flag if the
   completion wants it.
5. BINARY-vs-WIKI COOLDOWN DRIFT.  The binary channel atom
   (crowd-control-mobility.channel / VladimirE) carries cooldown rank1
   = 15.0 (values [15.0, 5.0, 550.0, 8192.0]) while the cached wiki
   cooldown row is 13/11/9/7/5 and the module reads the wiki array
   (HANDOVER §4.12 made this the certified behavior).  S1/S3 pin the
   wiki array; the 15.0 in the binary atom is a drift flag for patch
   day, not a runtime value.
6. STALE PER-ABILITY SOURCE REVISION.  The module SOURCES pin the E
   ability entry at revision 2864482 (2019-11-03) while the parent
   entry is 3960728 (2025-10-22) — the same stale-per-ability-revision
   pattern flagged for another champion's passive.  The row VALUES are current (they match
   the packet and the HANDOVER), but the per-ability revision should be
   re-pulled on the next patch day.
7. REFERENCE CONFIG NUMBERS.  The golden baseline's Vladimir E rows
   (scripts/golden_baseline.json) pin the LEVEL-11 entry: E rank 1,
   cooldown 13.0, total_raw 169.29 = (60 + 6% x 1565 rounded health +
   80% x 0 AP) x 1.1 hemoplague — i.e. the golden E numbers are the
   MAX-row values with the R debuff default ON and the level-11 rounded
   health.  Any completion change to the charge model's default
   (fraction 1.0 == max row) must re-capture the golden with every diff
   explained; the API-level reference numbers in S9 use the real
   level-18 stats (health 2470, AP 0).
"""

import hashlib
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.atomizer import hash_domain_file
from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.champions.slotlib import extract_value
from src.calculator.champions.vladimir import (
    MODULE_COVERAGE,
    PACKET_SHA256,
    _E_CHANNEL_SECONDS,
    _E_CHARGE_RAMP_SECONDS,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_VLADIMIR_DATA = _CHAMPION_DATA["Vladimir"]
_E_ABILITY = _VLADIMIR_DATA["abilities"]["E"][0]
_ABILITIES_ATOMS = json.loads(
    Path("data/atoms/abilities.json").read_text(encoding="utf-8")
)["objects"]["Vladimir"]
_CHAMPIONS_ATOMS = json.loads(
    Path("data/atoms/champions.json").read_text(encoding="utf-8")
)["objects"]["Vladimir"]
_MANIFEST = json.loads(Path("data/atoms/manifest.json").read_text(encoding="utf-8"))
_PACKET_VLADIMIR = json.loads(
    Path("static/reviewed-packets.json").read_text(encoding="utf-8")
)["champions"]["Vladimir"]
_RECEIPT_VLADIMIR_PATH = Path("docs/receipts/champions/vladimir.json")
_RECEIPT_VLADIMIR = (
    json.loads(_RECEIPT_VLADIMIR_PATH.read_text(encoding="utf-8"))
    if _RECEIPT_VLADIMIR_PATH.exists()
    else None
)

_AWAIT = "awaiting P4-Vladimir-E ..."
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_REF_HEALTH = 2500.0  # fabricated engine-level champion max health
_REF_AP = 100.0

# The cached leveling rows (rank 1..5, indexed rank-1).
_MIN_FLAT = [30, 45, 60, 75, 90]
_MAX_FLAT = [60, 90, 120, 150, 180]
_MIN_MAXHP = 1.5
_MAX_MAXHP = 6.0
_MIN_AP = 35.0
_MAX_AP = 80.0
_SLOW_ROW = [40, 45, 50, 55, 60]
_COOLDOWN_ROW = [13, 11, 9, 7, 5]


def _e_damage(rank: int, fraction: float, health: float, ap: float) -> float:
    """The contract formula: each modifier interpolates on its own."""
    flat = _MIN_FLAT[rank - 1] + (_MAX_FLAT[rank - 1] - _MIN_FLAT[rank - 1]) * fraction
    maxhp = _MIN_MAXHP + (_MAX_MAXHP - _MIN_MAXHP) * fraction
    ap_ratio = _MIN_AP + (_MAX_AP - _MIN_AP) * fraction
    return flat + maxhp / 100.0 * health + ap_ratio / 100.0 * ap


def _stats() -> dict:
    return {
        "attack_damage": 90.0,
        "ability_power": _REF_AP,
        "base_attack_damage": 90.0,
        "bonus_attack_damage": 0.0,
        "attack_speed": 0.658,
        "attack_speed_ratio": 0.658,
        "bonus_attack_speed": 0.0,
        "max_mana": 2.0,
        "resource_regen_per_second": 0.0,
        "level": 18,
        "health": _REF_HEALTH,
    }


def _parse(
    options: dict | None = None,
    ranks: dict | None = None,
    stats: dict | None = None,
):
    return parse_champion_abilities(
        get_champion("Vladimir"),
        18,
        _REF_AP,
        ability_ranks=ranks if ranks is not None else dict(_RANKS),
        champion_stats=stats if stats is not None else _stats(),
        target_stats={"target_max_health": _REF_HEALTH},
        champion_options=dict(options or {}),
    )


def _fight(
    options: dict,
    *,
    one_rotation: bool = True,
    duration: float = 10.0,
    score_only: bool = False,
    mr: float = 40.0,
    auto_attack_uptime: float = 0.0,
) -> dict:
    abilities = _parse(options)
    return calculate_fight_damage(
        _stats(),
        abilities,
        [],
        FightConfig(
            target_health=_REF_HEALTH,
            target_armor=50.0,
            target_magic_resistance=mr,
            fight_duration_seconds=duration,
            auto_attack_uptime=auto_attack_uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
        ),
        score_only=score_only,
        champion_options=dict(options),
    )


def _api(champion_options: dict | None = None) -> "object":
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Vladimir",
            "level": 18,
            "items": [],
            "role": "mid",
            "ability_ranks": _RANKS,
            "fight_mode": "one_rotation",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "target_health": 2500,
            "target_armor": 50,
            "target_mr": 0,
            "champion_options": champion_options or {},
        },
    )


def _leveling(attribute: str) -> dict:
    for effect in _E_ABILITY.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"no leveling {attribute!r} in Tides of Blood")


def _ability_atom(atom_id: str) -> dict:
    # timing.* ids are shared across abilities (W/R also carry
    # timing.active_duration); the E rows are always sourced from
    # Vladimir.E[0].
    matches = [
        atom
        for atom in _ABILITIES_ATOMS
        if atom["atom_id"] == atom_id and "E[0]" in atom.get("source", "")
    ]
    assert len(matches) == 1, f"ability atom {atom_id!r}: {len(matches)}"
    return matches[0]


def _champion_atom(atom_id: str, behavior: str | None = None) -> dict:
    matches = [
        atom
        for atom in _CHAMPIONS_ATOMS
        if atom["atom_id"] == atom_id
        and (behavior is None or atom.get("behavior") == behavior)
    ]
    assert len(matches) == 1, f"champion atom {atom_id!r} {behavior!r}: {len(matches)}"
    return matches[0]


def _packet_sha256(packet: dict) -> str:
    payload = json.dumps(
        packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# S1 - Source evidence (five E effects, leveling rows, atoms, module
#      declaration)
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_all_five_e_effects_verbatim(self):
        descriptions = [fx["description"] for fx in _E_ABILITY["effects"]]
        assert descriptions == [
            "Active: Vladimir charges for up to 1.5 seconds, during which he "
            "increases Tides of Blood's damage over the first second of the "
            "channel, and becomes slowed by 20% afterwards for the remaining "
            "duration. Tides of Blood can be recast within the duration, and "
            "does so automatically afterwards or if it is interrupted.",
            "Recast: Vladimir unleashes a nova of 15 blood bolts around "
            "himself that each deal magic damage to the first enemy hit, "
            "increased based on charge time up to the first second.",
            "If Tides of Blood was charged for at least 1 second, enemies "
            "hit are also slowed for 0.5 seconds.",
            "Enemies can intercept multiple bolts, but can be damaged only " "once.",
            "If Vladimir is below 12% of his maximum health, Tides of Blood "
            "will not cost any health.",
        ]

    def test_charge_time_effect_is_the_degraded_row(self):
        # effects[0] is the AGENTS.md degraded "Vladimir E (charge time)"
        # row: the charge-window prose with leveling EMPTY — the ramp is
        # never atomized; only the 1.5s channel survives in prose atoms.
        assert _E_ABILITY["effects"][0]["leveling"] == []
        assert _E_ABILITY["effects"][3]["leveling"] == []
        assert _E_ABILITY["effects"][4]["leveling"] == []

    def test_min_and_max_leveling_rows_pinned(self):
        minimum = _leveling("Minimum Magic Damage")
        maximum = _leveling("Maximum Magic Damage")
        assert [m["values"] for m in minimum["modifiers"]] == [
            _MIN_FLAT,
            [_MIN_MAXHP] * 5,
            [_MIN_AP] * 5,
        ]
        assert [m["units"] for m in minimum["modifiers"]] == [
            ["", "", "", "", ""],
            ["% maximum health"] * 5,
            ["% AP"] * 5,
        ]
        assert [m["values"] for m in maximum["modifiers"]] == [
            _MAX_FLAT,
            [_MAX_MAXHP] * 5,
            [_MAX_AP] * 5,
        ]

    def test_slow_leveling_row_pinned(self):
        slow = _leveling("Slow")
        assert slow["modifiers"][0]["values"] == _SLOW_ROW
        assert slow["modifiers"][0]["units"] == ["%"] * 5

    def test_cost_row_is_the_units_only_prose_carry(self):
        # The health cost is NOT a typed row: values are all zeros and the
        # 2/4/6/8% tiers live in the unit prose only.
        cost = _E_ABILITY["cost"]
        assert cost["modifiers"][0]["values"] == [0, 0, 0, 0, 0]
        assert (
            cost["modifiers"][0]["units"]
            == ["2% / 4% / 6% / 8% (based on " "charge time)"] * 5
        )
        assert _E_ABILITY["resource"] == "MAXIMUM_HEALTH"

    def test_cooldown_row_pinned(self):
        assert _E_ABILITY["cooldown"]["modifiers"][0]["values"] == _COOLDOWN_ROW
        assert _E_ABILITY["cooldown"]["affectedByCdr"] is True

    def test_e_notes_carry_cost_and_channel_boundaries(self):
        notes = _E_ABILITY["notes"]
        assert "15 blood bolts" in notes or "15 equally spaced missiles" in notes
        assert "health cost" in notes
        assert "below the specified amount" in notes

    def test_abilities_domain_atoms_pinned(self):
        expected = {
            "ability.minimum _magic _damage.modifier_0": "ed0a9a756a254ee9",
            "ability.minimum _magic _damage.modifier_1": "2241b298f6dcd8d4",
            "ability.minimum _magic _damage.modifier_2": "6c5d374d3795f5a8",
            "ability.maximum _magic _damage.modifier_0": "1e9f85c82f8835bf",
            "ability.maximum _magic _damage.modifier_1": "b80d1b0a647bec0f",
            "ability.maximum _magic _damage.modifier_2": "0b370081381fdce8",
            "ability.slow": "9542f5ef5b374978",
            "timing.active_duration": "367b90ae9fc5cf38",
            "timing.control_duration": "7e729d1075801443",
            "timing.cooldown": "15cbce498dc12195",
        }
        for atom_id, want in expected.items():
            atom = _ability_atom(atom_id)
            assert atom["hash"] == want, atom_id
            assert atom["name"] == "Tides of Blood"
        # The charge/duration atom IS the 1.5s channel (from the degraded
        # effects[0] prose); the 0.5s slow duration has its own atom.
        assert _ability_atom("timing.active_duration")["values"] == [1.5]
        assert _ability_atom("timing.control_duration")["values"] == [0.5]

    def test_no_atom_carries_the_one_second_ramp(self):
        # The ramp (1.0s) is the degraded row's missing half: every E
        # abilities-domain atom is listed above and none carries 1.0.
        e_atoms = [
            atom for atom in _ABILITIES_ATOMS if "E[0]" in atom.get("source", "")
        ]
        assert {atom["atom_id"] for atom in e_atoms} == {
            "ability.minimum _magic _damage.modifier_0",
            "ability.minimum _magic _damage.modifier_1",
            "ability.minimum _magic _damage.modifier_2",
            "ability.maximum _magic _damage.modifier_0",
            "ability.maximum _magic _damage.modifier_1",
            "ability.maximum _magic _damage.modifier_2",
            "ability.slow",
            "timing.active_duration",
            "timing.control_duration",
            "timing.cooldown",
        }
        assert all(1.0 not in atom["values"] for atom in e_atoms)

    def test_champions_domain_atoms_pinned(self):
        expected = {
            ("crowd-control-mobility.channel", "VladimirE"): "940d08fba719e658",
            ("crowd-control-mobility.slow", "VladimirESlow"): "35908e07efaea3a6",
            ("damage.aoe", "VladimirE"): "580c5d8ca6091984",
            ("damage.damage-instance", "VladimirE"): "75001ca6bfeeea3e",
            ("damage.damage-instance", "VladimirTidesofBloodNuke"): "2493ebc69f194d05",
            (
                "stack-transform-summon-resource.health-as-resource",
                "VladimirTidesofBloodCost",
            ): "77fd5d82b6181e37",
            ("heal-shield.heal", "VladimirTidesofBloodHeal"): "bba17d1afe12f8bd",
        }
        for (atom_id, behavior), want in expected.items():
            atom = _champion_atom(atom_id, behavior)
            assert atom["hash"] == want, (atom_id, behavior)
        # The channel atom is the charge/duration binary receipt; note the
        # binary cooldown rank1 is 15.0 vs the cached wiki 13.0 (AMBIGUITY 5).
        channel = _champion_atom("crowd-control-mobility.channel", "VladimirE")
        assert channel["values"] == [15.0, 5.0, 550.0, 8192.0]
        # The cost atom carries NO numbers (values empty) — the 2/4/6/8%
        # tiers are not atomized anywhere.
        cost = _champion_atom(
            "stack-transform-summon-resource.health-as-resource",
            "VladimirTidesofBloodCost",
        )
        assert cost["values"] == []

    def test_module_declaration_pinned(self):
        import src.calculator.champions.vladimir as vlad

        assert (
            PACKET_SHA256
            == "03e211424b005b94fe9d0df6d90a10efc1aa4d935e306143b14b0b254bd3532d"
        )
        assert MODULE_COVERAGE == {
            "P": "out_of_scope",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
        assert vlad.REVIEW_STATUS == "reviewed_module"
        assert set(vlad.SLOTS) == {"Q", "W", "E", "R", "P", "hemoplague"}
        assert _E_CHARGE_RAMP_SECONDS == 1.0
        assert _E_CHANNEL_SECONDS == 1.5

    def test_option_meta_declared(self):
        meta = get_champion_options_meta("Vladimir")
        charge = next(o for o in meta["options"] if o["key"] == "e_charge_fraction")
        assert charge["type"] == "float"
        assert charge["default"] == 1.0
        assert charge["min"] == 0.0
        assert charge["max"] == 1.0
        assert charge["step"] == 0.1
        assert "1s of the 1.5s channel" in charge["label"]
        assert any(o["key"] == "r_hemoplague_debuff" for o in meta["options"])
        assert any(
            "interpolates each sourced modifier" in text for text in meta["assumptions"]
        )
        assert any("40-60% slow" in text for text in meta["assumptions"])

    def test_reviewed_packet_e_slot_is_the_max_row(self):
        # The reviewed packet declares the MAX row (the module's
        # _tides_of_blood overrides it with the min/max interpolation;
        # fraction 1.0 reproduces the packet numbers exactly).
        spec = _PACKET_VLADIMIR["slots"]["E"]
        assert spec["kind"] == "packet"
        assert spec["base"] == [60.0, 90.0, 120.0, 150.0, 180.0]
        assert [r["values"] for r in spec["ratios"]] == [[0.06] * 5, [0.8] * 5]
        assert [r["stat"] for r in spec["ratios"]] == ["health", "ap"]


# ---------------------------------------------------------------------------
# S2 - Charge fractions (the interpolation) + the health cost at each
# ---------------------------------------------------------------------------


class TestChargeFractions:
    def test_zero_charge_prices_the_minimum_rows(self):
        entry = _parse({"e_charge_fraction": 0.0, "r_hemoplague_debuff": False})["E"]
        assert entry["total_raw"] == pytest.approx(162.5)
        assert entry["detail"] == (
            "0% charge (0s of the 1s ramp; 1.5s channel): flat 90 + "
            "1.5% maximum health + 35% AP"
        )

    def test_half_charge_interpolates_each_modifier(self):
        entry = _parse({"e_charge_fraction": 0.5, "r_hemoplague_debuff": False})["E"]
        assert entry["total_raw"] == pytest.approx(286.25)
        assert entry["detail"] == (
            "50% charge (0.5s of the 1s ramp; 1.5s channel): flat 135 + "
            "3.75% maximum health + 57.5% AP"
        )

    def test_full_charge_prices_the_maximum_rows(self):
        entry = _parse({"e_charge_fraction": 1.0, "r_hemoplague_debuff": False})["E"]
        assert entry["total_raw"] == pytest.approx(410.0)
        assert entry["detail"] == (
            "100% charge (1s of the 1s ramp; 1.5s channel): flat 180 + "
            "6% maximum health + 80% AP"
        )

    def test_default_fraction_is_fully_charged(self):
        # The option default 1.0 reproduces the reviewed packet's max-row
        # numbers exactly (no champion_options at all).
        default = _parse({"r_hemoplague_debuff": False})["E"]
        explicit = _parse({"e_charge_fraction": 1.0, "r_hemoplague_debuff": False})["E"]
        assert default["total_raw"] == explicit["total_raw"] == pytest.approx(410.0)

    def test_interpolation_is_per_modifier_not_uniform(self):
        # flat x2, %maxHP x4, %AP ~x2.3 between the rows — a single
        # uniform scale would price a different total; each modifier
        # interpolates on its own (the module's HARDCODED note).
        entry = _parse({"e_charge_fraction": 0.25, "r_hemoplague_debuff": False})["E"]
        assert entry["total_raw"] == pytest.approx(224.375)
        assert entry["detail"] == (
            "25% charge (0.25s of the 1s ramp; 1.5s channel): flat 112.5 + "
            "2.625% maximum health + 46.25% AP"
        )
        assert entry["total_raw"] == pytest.approx(
            _e_damage(5, 0.25, _REF_HEALTH, _REF_AP)
        )

    def test_health_cost_is_unpriced_at_every_fraction(self):
        # The 2%/4%/6%/8% current-health cost is NOT modeled: no
        # resource_cost on the parse entry and zero resource spent in the
        # fight, at every fraction (live guard; the seam is S5's xfail).
        for fraction in (0.0, 0.5, 1.0):
            options = {"e_charge_fraction": fraction, "r_hemoplague_debuff": False}
            entry = _parse(options)["E"]
            assert "resource_cost" not in entry, fraction
            result = _fight(options, one_rotation=True, mr=0.0)
            assert result["resource_spent"] == 0.0
            assert result["resource_remaining"] == 0.0
            for row in result["cast_timeline"]:
                if row.get("slot") == "E":
                    assert row["resource_cost"] == 0.0

    def test_health_cost_boundary_receipt(self):
        # The typed cost seam: 2% of CURRENT health at fraction 0, 8% at
        # fraction 1.0, monotone between (the 4%/6% tier boundaries are
        # not sourced — AMBIGUITY 3; only endpoints are pinned here).
        from src.calculator.champions.vladimir import E_HEALTH_COST_RULE  # noqa: F401

        receipt = E_HEALTH_COST_RULE.public_receipt()["health_cost"]
        assert receipt["cost_percent_at_min_charge"] == pytest.approx(2.0)
        assert receipt["cost_percent_at_max_charge"] == pytest.approx(8.0)
        assert receipt["source"]["wiki"]["revision_id"] == 2864482


# ---------------------------------------------------------------------------
# S3 - Level endpoints (min/max rows at ranks 1-5)
# ---------------------------------------------------------------------------


class TestLevelEndpoints:
    def test_min_rows_at_ranks_1_to_5(self):
        for rank in range(1, 6):
            entry = _parse(
                {"e_charge_fraction": 0.0, "r_hemoplague_debuff": False},
                ranks={**dict(_RANKS), "E": rank},
            )["E"]
            want = _e_damage(rank, 0.0, _REF_HEALTH, _REF_AP)
            assert entry["total_raw"] == pytest.approx(want), rank
            assert entry["rank"] == rank

    def test_max_rows_at_ranks_1_to_5(self):
        for rank in range(1, 6):
            entry = _parse(
                {"e_charge_fraction": 1.0, "r_hemoplague_debuff": False},
                ranks={**dict(_RANKS), "E": rank},
            )["E"]
            want = _e_damage(rank, 1.0, _REF_HEALTH, _REF_AP)
            assert entry["total_raw"] == pytest.approx(want), rank
            assert entry["rank"] == rank

    def test_endpoint_totals_pinned(self):
        # Rank 1..5 max: 290/320/350/380/410; min: 102.5/117.5/132.5/
        # 147.5/162.5 at AP 100 / health 2500.
        for rank, want_max, want_min in zip(
            range(1, 6),
            (290.0, 320.0, 350.0, 380.0, 410.0),
            (102.5, 117.5, 132.5, 147.5, 162.5),
        ):
            ranks = {**dict(_RANKS), "E": rank}
            entry_max = _parse(
                {"e_charge_fraction": 1.0, "r_hemoplague_debuff": False},
                ranks=ranks,
            )["E"]
            entry_min = _parse(
                {"e_charge_fraction": 0.0, "r_hemoplague_debuff": False},
                ranks=ranks,
            )["E"]
            assert entry_max["total_raw"] == pytest.approx(want_max)
            assert entry_min["total_raw"] == pytest.approx(want_min)

    def test_e_cooldown_tracks_the_live_cached_array(self):
        # The module reads the live cooldown row 13/11/9/7/5 — NOT the
        # reviewed packet's fixed 13.0 (HANDOVER §4.12).
        for rank, want in zip(range(1, 6), _COOLDOWN_ROW):
            entry = _parse(
                {"r_hemoplague_debuff": False},
                ranks={**dict(_RANKS), "E": rank},
            )["E"]
            assert entry["cooldown"] == pytest.approx(want), rank

    def test_unranked_e_is_absent(self):
        abilities = _parse(ranks={k: 0 for k in "QWER"})
        assert "E" not in abilities


# ---------------------------------------------------------------------------
# S4 - The charge window (1.5s channel vs the 1s ramp)
# ---------------------------------------------------------------------------


class TestChargeWindow:
    def test_channel_constant_matches_the_sourced_atom(self):
        # 1.5s = the atomized channel (timing.active_duration from the
        # degraded effects[0] prose "charges for up to 1.5 seconds").
        assert _E_CHANNEL_SECONDS == 1.5
        assert _ability_atom("timing.active_duration")["values"] == [1.5]
        assert (
            "charges for up to 1.5 seconds" in _E_ABILITY["effects"][0]["description"]
        )

    def test_ramp_constant_is_the_unsourced_degraded_row_half(self):
        # 1.0s = the ramp, wiki prose only: "increases Tides of Blood's
        # damage over the first second of the channel" (effects[0]) and
        # "increased based on charge time up to the first second"
        # (effects[1]).  No atom carries 1.0 (S1) — the module constant
        # is the only home, with the "verify on patch updates" comment.
        assert _E_CHARGE_RAMP_SECONDS == 1.0
        assert (
            "over the first second of the channel"
            in _E_ABILITY["effects"][0]["description"]
        )
        assert "up to the first second" in _E_ABILITY["effects"][1]["description"]

    def test_detail_carries_the_window_semantics(self):
        # fraction maps linearly onto the 1s ramp (fraction == fraction
        # seconds of ramp) inside the 1.5s channel; the detail string is
        # the receipt consumers see.
        entry = _parse({"e_charge_fraction": 0.5, "r_hemoplague_debuff": False})["E"]
        assert "0.5s of the 1s ramp" in entry["detail"]
        assert "1.5s channel" in entry["detail"]
        entry_full = _parse({"e_charge_fraction": 1.0, "r_hemoplague_debuff": False})[
            "E"
        ]
        assert "1s of the 1s ramp" in entry_full["detail"]

    def test_slow_boundary_is_the_ramp_completion(self):
        # effects[2]: "charged for at least 1 second" == the ramp
        # completed == fraction 1.0.  The slow exists only at full
        # charge; below it the enemy takes the interpolated nova with no
        # slow (the seam's boundary semantics — S6 xfail).
        assert (
            "charged for at least 1 second" in _E_ABILITY["effects"][2]["description"]
        )
        assert _E_CHARGE_RAMP_SECONDS == 1.0


# ---------------------------------------------------------------------------
# S5 - Health cost + the 12% free rule
# ---------------------------------------------------------------------------


class TestHealthCostFreeRule:
    def test_free_rule_effect_verbatim(self):
        assert _E_ABILITY["effects"][4]["description"] == (
            "If Vladimir is below 12% of his maximum health, Tides of "
            "Blood will not cost any health."
        )

    def test_cost_notes_verbatim(self):
        # The notes' per-tick semantics: the cost ticks can drop Vladimir
        # below the free threshold mid-channel; later ticks stop.
        assert "below the specified amount" in _E_ABILITY["notes"]
        assert "every tick of health cost" in _E_ABILITY["notes"]

    def test_health_cost_is_not_modeled_today(self):
        # Live guard: no resource_cost on the E entry, zero resource
        # spent, no resource ledger — the 12% free rule is a named
        # boundary with no typed seam.
        options = {"e_charge_fraction": 1.0, "r_hemoplague_debuff": False}
        assert "resource_cost" not in _parse(options)["E"]
        result = _fight(options, one_rotation=True)
        assert result["resource_spent"] == 0.0
        assert result["resource_ledger"] is None

    def test_free_rule_boundary_receipt(self):
        # A typed cost seam must expose the free boundary: no health cost
        # when the caster's current health is below 12% of max health
        # (effects[4]); the engine has no attacker current-health input
        # today (AMBIGUITY 3), so the seam needs one.
        from src.calculator.champions.vladimir import E_HEALTH_COST_RULE  # noqa: F401

        receipt = E_HEALTH_COST_RULE.public_receipt()["health_cost"]
        assert receipt["free_below_fraction_of_max_health"] == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# S6 - The slow (0.5s + the rank values)
# ---------------------------------------------------------------------------


class TestSlow:
    def test_slow_effect_and_row_verbatim(self):
        assert _E_ABILITY["effects"][2]["description"] == (
            "If Tides of Blood was charged for at least 1 second, enemies "
            "hit are also slowed for 0.5 seconds."
        )
        slow = _leveling("Slow")
        assert slow["modifiers"][0]["values"] == _SLOW_ROW
        assert _ability_atom("ability.slow")["values"] == [float(v) for v in _SLOW_ROW]
        assert _ability_atom("timing.control_duration")["values"] == [0.5]

    def test_no_slow_surface_today(self):
        # Live guard: the E part carries no cc, the fight emits no
        # control events, and the module ASSUMPTION names the slow
        # "utility" (unmodeled).
        entry = _parse({"e_charge_fraction": 1.0, "r_hemoplague_debuff": False})["E"]
        assert all(getattr(part, "cc_kind", None) is None for part in entry["parts"])
        result = _fight({"e_charge_fraction": 1.0, "r_hemoplague_debuff": False})
        assert result["control_events"] == []
        meta = get_champion_options_meta("Vladimir")
        assert any("40-60% slow" in text for text in meta["assumptions"])

    def test_slow_utility_boundary_receipt(self):
        # The enemy slow: rank values for 0.5s, ONLY at fraction 1.0
        # ("charged for at least 1 second" == ramp completion); below
        # full charge the interpolated nova carries no slow.
        from src.calculator.champions.vladimir import E_SLOW_RULE  # noqa: F401

        receipt = E_SLOW_RULE.public_receipt()["slow"]
        assert receipt["slow_level_1"] == pytest.approx(40.0)
        assert receipt["slow_level_5"] == pytest.approx(60.0)
        assert receipt["duration_seconds"] == pytest.approx(0.5)
        assert receipt["requires_full_ramp"] is True
        assert receipt["source"]["wiki"]["revision_id"] == 2864482


# ---------------------------------------------------------------------------
# S7 - Malformed/stale declarations (degraded row, option bounds)
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_min_max_rows_resolve_by_exact_attribute_name(self):
        # The module reads the rows by exact attribute name; the degraded
        # charge-time row (effects[0]) is never read — the fraction IS
        # the selection.  Values resolve exactly, never a zero fallback.
        for rank, want in zip(range(1, 6), _MIN_FLAT):
            assert extract_value(
                _E_ABILITY, "Minimum Magic Damage", rank, 0
            ) == pytest.approx(want)
        for rank, want in zip(range(1, 6), _MAX_FLAT):
            assert extract_value(
                _E_ABILITY, "Maximum Magic Damage", rank, 0
            ) == pytest.approx(want)
        assert extract_value(_E_ABILITY, "Minimum Magic Damage", 5, 1) == pytest.approx(
            1.5
        )
        assert extract_value(_E_ABILITY, "Maximum Magic Damage", 5, 2) == pytest.approx(
            80.0
        )

    def test_parse_clamps_out_of_range_fraction(self):
        # Direct-parse path: the module clamps to [0, 1] (a defensive
        # clamp; the API 400s instead — S9).
        over = _parse({"e_charge_fraction": 2.0, "r_hemoplague_debuff": False})["E"]
        assert over["total_raw"] == pytest.approx(410.0)
        assert "100% charge" in over["detail"]
        under = _parse({"e_charge_fraction": -1.0, "r_hemoplague_debuff": False})["E"]
        assert under["total_raw"] == pytest.approx(162.5)
        assert "0% charge" in under["detail"]

    def test_parse_non_numeric_fraction_raises(self):
        with pytest.raises(ValueError):
            _parse({"e_charge_fraction": "not-a-number"})

    def test_unknown_option_ignored_at_parse_level(self):
        # Direct parse ignores undeclared keys (no validation there); the
        # API layer 400s them (S9).
        entry = _parse({"bogus_key": True, "r_hemoplague_debuff": False})["E"]
        assert entry["total_raw"] == pytest.approx(410.0)

    def test_option_meta_bounds_are_declared(self):
        meta = get_champion_options_meta("Vladimir")
        charge = next(o for o in meta["options"] if o["key"] == "e_charge_fraction")
        assert charge["min"] == 0.0
        assert charge["max"] == 1.0
        assert charge["default"] == 1.0
        assert charge["type"] == "float"
        # The option is consumed by the module source (the parser reads
        # ctx.options["e_charge_fraction"]).
        import inspect

        from src.calculator.champions import vladimir as vladimir_module

        source = inspect.getsource(vladimir_module)
        assert 'ctx.options.get("e_charge_fraction"' in source


# ---------------------------------------------------------------------------
# S8 - Source + atom receipts (hashes + SOURCES)
# ---------------------------------------------------------------------------


class TestSourceAndAtomReceipts:
    def test_atom_hashes_are_stable(self):
        # Pinned above in S1; re-pin the four most drift-prone rows here.
        assert (
            _ability_atom("ability.minimum _magic _damage.modifier_0")["hash"]
            == "ed0a9a756a254ee9"
        )
        assert (
            _ability_atom("ability.maximum _magic _damage.modifier_0")["hash"]
            == "1e9f85c82f8835bf"
        )
        assert _ability_atom("ability.slow")["hash"] == "9542f5ef5b374978"
        assert _ability_atom("timing.active_duration")["hash"] == "367b90ae9fc5cf38"

    def test_manifest_receipts_match_the_on_disk_files(self):
        # The atoms manifest digests: rather than pinning a literal (which
        # trips on every legitimate re-atomization), each manifest sha256
        # is verified against a RECOMPUTED content-stable hash of the
        # on-disk domain file (atomizer.hash_domain_file) — stronger than
        # a literal because it checks the actual bytes every run.
        domains = _MANIFEST["domains"]
        assert domains["champions"]["object_count"] == 173
        for domain in ("champions", "stats", "abilities"):
            assert domains[domain]["sha256"] == hash_domain_file(
                Path(f"data/atoms/{domain}.json")
            )
        actual = hashlib.sha256(Path("data/champions.json").read_bytes()).hexdigest()
        assert domains["champions"]["source_ref"].endswith(
            f"data/champions.json@sha256:{actual[:16]};data/bin/characters"
        )

    def test_packet_spec_digests_to_the_module_hash(self):
        assert _packet_sha256(_PACKET_VLADIMIR) == PACKET_SHA256

    def test_module_sources_pin_wiki_revisions(self):
        meta = get_champion_options_meta("Vladimir")
        assert len(meta["sources"]) == 6  # parent + P/Q/W/E/R entries
        sources = {row["label"]: row for row in meta["sources"]}
        parent = sources["Vladimir parent entry"]
        assert parent["url"] == "https://wiki.leagueoflegends.com/en-us/Vladimir"
        assert parent["revision_id"] == 3960728
        assert parent["revision_timestamp"] == "2025-10-22T22:09:57Z"
        e_entry = sources["Vladimir E ability entry"]
        assert (
            e_entry["url"]
            == "https://wiki.leagueoflegends.com/en-us/Template:Data_Vladimir/E"
        )
        assert e_entry["revision_id"] == 2864482  # STALE (AMBIGUITY 6)
        assert e_entry["revision_timestamp"] == "2019-11-03T20:13:56Z"

    def test_receipts_document_thirty_six_atoms(self):
        if _RECEIPT_VLADIMIR is None:
            pytest.skip("generated Vladimir receipt is unavailable")
        assert _RECEIPT_VLADIMIR["champion"] == "Vladimir"
        assert _RECEIPT_VLADIMIR["atoms"]["count"] == 36
        assert set(_RECEIPT_VLADIMIR["atoms"]["families"]) == {
            "crowd-control-mobility",
            "damage",
            "heal-shield",
            "stack-transform-summon-resource",
        }
        assert _RECEIPT_VLADIMIR["audit_verdict"] == "ok"

    def test_typed_charge_model_certification(self):
        # Mirror the repo's typed-rule-with-public-receipt pattern: a
        # public receipt for the charge model exposing the ramp/channel
        # constants, the
        # default fraction, and the atom ids it is backed by — with the
        # wiki prose named as the 1s-ramp root (no atom carries it,
        # AMBIGUITY 2).
        from src.calculator.champions.vladimir import E_CHARGE_RULE  # noqa: F401

        receipt = E_CHARGE_RULE.public_receipt()
        assert receipt["ramp_seconds"] == pytest.approx(1.0)
        assert receipt["channel_seconds"] == pytest.approx(1.5)
        assert receipt["default_fraction"] == pytest.approx(1.0)
        assert (
            "timing.active_duration"
            in receipt["atom_ids"]["channel_seconds"]["atom_id"]
        )
        assert (
            "ability.minimum _magic _damage.modifier_0"
            in receipt["atom_ids"]["min_modifier_0"]["atom_id"]
        )
        assert (
            "ability.maximum _magic _damage.modifier_0"
            in receipt["atom_ids"]["max_modifier_0"]["atom_id"]
        )
        assert receipt["ramp_source"]  # names the wiki prose root


# ---------------------------------------------------------------------------
# S9 - API validation (accepted + applied; unknown / out-of-range 400)
# ---------------------------------------------------------------------------


class TestApiValidation:
    # API fights use the REAL level-18 stats: health 2470 (600 + 110x17),
    # AP 0.  Expected rank-5 E nova: frac 0 = 90 + 1.5% x 2470 = 127.05;
    # frac 0.5 = 135 + 3.75% x 2470 = 227.625; frac 1 = 180 + 6% x 2470 =
    # 328.2 (MR 0, debuff off, one cast; rows rounded to 1dp).
    @staticmethod
    def _expected(frac: float) -> float:
        return (
            90.0 + (180.0 - 90.0) * frac + (1.5 + (6.0 - 1.5) * frac) / 100.0 * 2470.0
        )

    def test_api_accepts_charge_fraction_and_applies(self):
        response = _api({"e_charge_fraction": 0.5, "r_hemoplague_debuff": False})
        assert response.status_code == 200
        body = response.get_json()
        e_row = body["breakdown"]["E"]
        assert e_row["name"] == "Tides of Blood"
        assert e_row["casts"] == 1
        assert e_row["total_damage"] == pytest.approx(self._expected(0.5), abs=0.06)
        assert "50% charge" in e_row["detail"]

    def test_api_fraction_changes_the_e_row(self):
        rows = {}
        for fraction in (0.0, 0.5, 1.0):
            response = _api(
                {"e_charge_fraction": fraction, "r_hemoplague_debuff": False}
            )
            assert response.status_code == 200
            rows[fraction] = response.get_json()["breakdown"]["E"]["total_damage"]
        assert rows[0.0] == pytest.approx(self._expected(0.0), abs=0.06)
        assert rows[0.5] == pytest.approx(self._expected(0.5), abs=0.06)
        assert rows[1.0] == pytest.approx(self._expected(1.0), abs=0.06)
        assert rows[0.0] < rows[0.5] < rows[1.0]

    def test_api_bounds_are_inclusive(self):
        for fraction in (0.0, 1.0, 0, 1):
            response = _api(
                {"e_charge_fraction": fraction, "r_hemoplague_debuff": False}
            )
            assert response.status_code == 200, fraction

    def test_api_unknown_option_400(self):
        response = _api({"unknown_key": True})
        assert response.status_code == 400
        assert (
            "champion_options contains unknown option unknown_key"
            in response.get_json()["error"]
        )

    def test_api_out_of_range_400(self):
        for fraction in (1.5, -0.5):
            response = _api({"e_charge_fraction": fraction})
            assert response.status_code == 400, fraction
            assert (
                "e_charge_fraction must be between 0.0 and 1.0"
                in response.get_json()["error"]
            )

    def test_api_non_numeric_400(self):
        response = _api({"e_charge_fraction": "not-a-number"})
        assert response.status_code == 400
        assert "e_charge_fraction must be a number" in response.get_json()["error"]

    def test_api_hemoplague_default_scales_e_by_ten_percent(self):
        # The R debuff (default ON) amplifies the charged E by exactly
        # 1.1 on top of the interpolation.
        base = _api(
            {"e_charge_fraction": 0.5, "r_hemoplague_debuff": False}
        ).get_json()["breakdown"]["E"]["total_damage"]
        amped = _api({"e_charge_fraction": 0.5}).get_json()["breakdown"]["E"][
            "total_damage"
        ]
        assert amped == pytest.approx(base * 1.1, abs=0.06)


# ---------------------------------------------------------------------------
# S10 - Score/receipt parity (full vs score_only byte-identical)
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_full_vs_score_only_byte_identical_one_rotation(self):
        for fraction in (0.0, 0.5, 1.0):
            options = {"e_charge_fraction": fraction, "r_hemoplague_debuff": False}
            full = _fight(options, one_rotation=True)
            scored = _fight(options, one_rotation=True, score_only=True)
            assert full["breakdown"] == scored["breakdown"], fraction
            assert full["total_damage"] == scored["total_damage"], fraction
            assert full["resource_spent"] == scored["resource_spent"], fraction
            assert full["resource_remaining"] == scored["resource_remaining"], fraction
            assert full["resource_ledger"] == scored["resource_ledger"], fraction
            assert full["notes"] == scored["notes"], fraction
            shared = ("time", "slot", "name", "ordinal", "resource_cost")
            assert len(full["cast_timeline"]) == len(scored["cast_timeline"])
            for full_row, scored_row in zip(
                full["cast_timeline"], scored["cast_timeline"]
            ):
                assert {k: full_row[k] for k in shared} == {
                    k: scored_row[k] for k in shared
                }, fraction

    def test_full_vs_score_only_byte_identical_timed(self):
        for fraction in (0.0, 0.5, 1.0):
            options = {"e_charge_fraction": fraction, "r_hemoplague_debuff": False}
            full = _fight(options, one_rotation=False, duration=10.0)
            scored = _fight(options, one_rotation=False, duration=10.0, score_only=True)
            assert full["breakdown"] == scored["breakdown"], fraction
            assert full["total_damage"] == scored["total_damage"], fraction
            assert full["resource_ledger"] == scored["resource_ledger"], fraction

    def test_full_vs_score_only_byte_identical_with_hemoplague_default(self):
        options = {"e_charge_fraction": 0.5}  # debuff default ON
        full = _fight(options, one_rotation=True)
        scored = _fight(options, one_rotation=True, score_only=True)
        assert full["breakdown"] == scored["breakdown"]
        assert full["total_damage"] == scored["total_damage"]


# ---------------------------------------------------------------------------
# S11 - Regression surface (kept green; run list)
# ---------------------------------------------------------------------------


class TestRegressionSurface:
    def test_vladimir_grep_surface_is_pinned(self):
        # Every tests/ file mentioning "vladimir" (case-insensitive):
        # adding a new Vladimir test file must extend this pin, and every
        # listed file must stay green in the sanity run.
        test_dir = Path("tests")
        hits = sorted(
            path.name
            for path in test_dir.glob("test_*.py")
            if "vladimir" in path.read_text(encoding="utf-8", errors="ignore").lower()
        )
        assert hits == [
            "test_cp10_batch_09.py",
            "test_e2_dot_3.py",
            "test_e9_corpus.py",
            "test_f2_rotation.py",
            "test_f3_rotation_all.py",
            "test_heal_ledger_phase2.py",
            "test_issue_143.py",
            "test_mechanics_packets.py",
            "test_p1_review_3.py",
            "test_participant_timeline.py",
            "test_vladimir_e_charge_time.py",
            "test_vladimir_healing.py",
        ]

    def test_module_meta_pins_unchanged(self):
        meta = get_champion_options_meta("Vladimir")
        assert [option["key"] for option in meta["options"]] == [
            "e_charge_fraction",
            "r_hemoplague_debuff",
        ]
        assert any("Tides of Blood" in text for text in meta["assumptions"])
        assert any("Hemoplague" in text for text in meta["assumptions"])
        assert MODULE_COVERAGE["E"] == "modeled"
        assert MODULE_COVERAGE["P"] == "out_of_scope"
        assert MODULE_COVERAGE["R"] == "modeled"


# ---------------------------------------------------------------------------
# Sanity run list (contract 11) - run ONLY this file plus the mandated
# sanity set from the coordinator brief (the same list the sibling
# matrices' footers carry: the game-file verification, Q3 crit
# conversion, stardust, relic-cannon, harrier-crit, execute-range,
# mana-restore/refund, resource-ledger, catalyst, item-sustain,
# champion-options, and app suites).  The sibling files are NOT named
# here so the sibling regression-surface pins (which scan every test
# file's text for their champion name) stay green.
# Excluded from the run list: the golden snapshot gate (coordinator-owned)
# and tests/test_mechanics_packets.py::TestVladimirECharge (already covered
# here; it stays green as part of the regression surface).
