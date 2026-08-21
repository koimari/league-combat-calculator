"""P4 - Zeri P "Living Battery" execute range (test-matrix owner: RLM-2 C).

Focused TDD matrix for the UNCHARGED zap's execute threshold
(70 : 170.59 by level + 20% AP).  CURRENT RUNTIME FACTS
(verify-before-pin completed, all pinned in S1):

- The cached P (data/champions.json "Zeri" -> abilities.P[0]) has THREE
  effects: [0] the charge-generator prose (leveling EMPTY), [1] the
  UNCHARGED zap - "Per-Level Scaling" 20-value zap-damage row
  (10 .. 27.35) plus "Bonus Damage" 20-value EXECUTE-THRESHOLD row
  (70 .. 170.59) plus a second modifier [20.0] "% AP" - and [2] the
  FULL-CHARGE attack (75 .. 170 + 110% AP + 1% .. 12.18% max HP; the
  monster cap is 300; NAMED OUT-OF-SCOPE boundary).  The 20-value rows
  are indexed by LEVEL (rank == level for this packet; the 70..170.59
  range IS the row: level 1 = 70, level 20 = 170.59 - there is no
  4-value row in the cache; the parent brief's "4 values" were the
  first four entries of each row).
- DEGRADED PARSE (the AGENTS.md known-degraded list: "Zeri P (execute
  range)"): both 20-value rows survive with all-empty ``units`` (the
  half-parse signature: values survive, units come back empty), so the
  generic parser cannot ATTRIBUTE them; the "[20.0] '% AP'" modifier
  parsed with its unit intact.  The empty unit resolves as FLAT
  (``is_flat_unit("")``), so a named module reading "Bonus Damage" via
  the engine extractor gets exactly row[level-1] + 0.2 x AP (pinned in
  S2/S3).
- The module (src/calculator/champions/zeri.py) ships Q/W/E/R plus a
  PACKET P slot (static/reviewed-packets.json, sha
  f03ac495eb30baef9672e60deb2f448b0da551e22e39c3113cbc0cfee9e1c055):
  kind "packet", name "Living Battery", base = TWENTY ZEROS (the zap
  row is NOT declared), ratios = [targetMaxHp 1% .. 12.18%] (the
  FULL-CHARGE %maxHP curve, MISATTRIBUTED to the P slot), ranks
  "level".  Parse emits a zero-damage "passive" entry at every level
  (total_raw 0.0, rank == level, name "Living Battery"); the fight
  drops it entirely (no breakdown row, no damage, no execute surface).
- The engine's execute seam is execute_threshold_ratio/execute_source
  (Syndra R 0.15 / The Collector): damage.py stamps each event of an
  ability whose entry carries the ratio; survival/transitions.py turns
  the stamped event into a TERMINAL death when
  ``pools.health <= pools.max_health * ratio`` - evaluated AFTER the
  event's own damage (the zap's damage counts toward the threshold),
  INCLUSIVE at the boundary.  Zeri's threshold is an ABSOLUTE flat
  health value, not a max-health ratio; whether the completion hosts it
  through a parse-time ratio conversion (threshold / target_max_health
  - exact math, but the stamped ratio becomes target-dependent) or a
  new absolute-health typed key is the coordinator's seam decision
  (see AMBIGUITIES 2/4).
- Atoms (data/atoms/champions.json object "Zeri"): NO atom carries the
  threshold numbers.  The binary catalog has damage.execute rule flags
  only on ZeriQ / ZeriQMis (hashes 6013648e7780edb2 / 3a119ecc1dcad01d,
  values are timing/bitmask, no threshold) and a damage.basic-attack
  atom for ZeriPassive (hash 288e9c6b195123cb, values [0.0]).  The
  70..170.59 curve + 20% AP exist ONLY in the wiki JSON.  The module
  source receipt pins the parent entry at revision 4019486
  (2026-05-17) and the P ability entry at revision 3380499
  (2022-01-07 - STALE per-ability revision, flagged).

CONTRACT PINNED HERE (the P4-Zeri-P completion must satisfy;
genuinely-unsupported boundaries are STRICT xfails with reason
"awaiting P4-Zeri-P ..." - the coordinator flips each xfail to a live
test when the seam lands):

- S1  Source evidence: all three P effect descriptions verbatim, the
      notes verbatim, the leveling rows (the 20-value zap row + the
      20-value threshold row + the 20% AP modifier, the full-charge
      rows), cost/targeting/resource, the module declaration (packet
      spec P slot, PACKET_SHA256 == manifest digest, MODULE_COVERAGE,
      meta options/sources), the atoms (ids + hashes; the degraded
      state), the zero-damage passive parse at every level.
- S2  Level endpoints + middle: the threshold row at levels
      1/6/11/18/20 = 70 / 96.47 / 122.94 / 160 / 170.59 (level
      indexing row[level-1]; the row is the full 1..20 curve); the
      engine extractor resolves the degraded row exactly; XFAIL: the
      parse entry's execute surface equals the row value at each level.
- S3  AP 0/nonzero: the 20% AP term at AP 0/100/500 (+0/+20/+100;
      e.g. level 18: 160 / 180 / 260, level 20: 170.59 / 190.59 /
      270.59); XFAIL: the parse entry's surface carries the AP term.
- S4  Below / equal / above the threshold: with only the P in the
      fight (ranks 0 - no other damage source), the target dies when
      its health <= threshold (INCLUSIVE equality - the engine's
      ``<=`` convention and the client brief "current health <=
      threshold"; the wiki prose says "below" - see AMBIGUITY 3), and
      survives above.  Reference: level 18, AP 0, threshold 160,
      MR 0: 159.99 -> execute, 160.00 -> execute, 160.01 -> no.
      XFAIL for below/equal (no seam exists today - nothing executes);
      the above-threshold half already holds and is a LIVE PASS guard
      the completion must keep true.
- S5  Uncharged vs full-charge boundary: the execute range belongs to
      the UNCHARGED zap (effects[1]); the full-charge attack
      (effects[2]) is the named out-of-scope boundary; today the P
      packet MISATTRIBUTES the full-charge %maxHP ratio to the P slot
      while pricing zero damage (pinned); the unpriced state is a LIVE
      PASS guard (the completion's seam must never re-price the
      full-charge %maxHP term or its execute).
- S6  Malformed/stale/ambiguous fail-closed: the degraded row still
      resolves exactly (values survive; empty units are flat - never a
      zero fallback); no atom carries the threshold (nothing to go
      stale); unknown champion_options are 400'd with a named receipt
      (Zeri declares NO options); the passive prices zero damage at
      every level; the stale P source revision is pinned so patch-day
      review trips it.
- S7  Atom/source receipts: the Zeri atom hashes, the champions-domain
      manifest receipt (sha256 49e1c1ddcb91244a, source_ref
      data/champions.json@sha256:afea81a9976904c1;data/bin/characters
      - actual file hash verified), the module PACKET_SHA256 vs the
      recomputed manifest digest, the module SOURCES revisions; XFAIL:
      the typed atom-backed certification of the threshold (the
      completion's "typed atom-backed values" rule) - genuinely
      unsupported today because NO atom/binary root carries the
      numbers; the completion must name the wiki row as the root.
- S8  API output: /api/calculate for Zeri today is 200 with NO execute
      surface (no execute* keys, no passive breakdown row, damage
      events carry no execute stamps); XFAIL: the P execute surface
      appears (breakdown P row with an "Executes below ..." detail, the
      repo's Asol-E precedent, and/or stamped damage events).
- S9  Score/receipt parity: full vs score_only byte-identical on the
      scored surface (one-rotation and timed) - PASSES today (no P
      surface to diverge).
- S10 Regression surface: the tests/ grep set for "zeri" is pinned to
      exactly {test_spellblade_on_hit_matrix, test_e5_fix_2,
      test_cp10_batch_10, test_e2_dot_3, test_zeri_p_execute_range}
      (growing the set requires updating this pin); module meta pins;
      the mandated sanity list (footer).

AMBIGUITY NOTES for the coordinator:

1. THE ROW IS 20 VALUES, NOT 4.  The parent brief's "the row has 4
   values vs the 70..170.59 range" is resolved: the cached leveling
   rows are the full 20-value level curve (level cap is 20).  The
   threshold is row[level-1] + 20% AP; level 1 = 70, level 20 =
   170.59.  There is no separate 4-value array anywhere in the cached
   P.  (The cost row [0,0,0] units "10 \u2022 100" is the charge
   mechanic, unrelated.)
2. SEAM SHAPE: the engine's execute_threshold_ratio is a max-health
   RATIO; Zeri's threshold is an ABSOLUTE flat health value.  The
   smallest seam is either (a) parse-time conversion ratio =
   threshold / ctx.target["target_max_health"] (arithmetically exact -
   verified round-trip for 160/2358 etc. - but the stamped ratio is
   target-dependent and semantically misleading in events), or (b) a
   new absolute typed key (e.g. execute_threshold_health) alongside
   the ratio in engine.py's allowed keys + transitions.py + damage.py
   stamping.  (b) is the honest seam; (a) is the smallest.  The S2/S4
   xfails assert the VALUE (160 at level 18 AP 0) and the BEHAVIOR
   (dies at health <= 160), not the key, so either lands them.
3. EQUALITY SEMANTICS: the engine's ratio seam uses ``<=``
   (inclusive; executes AT the threshold), the wiki prose says
   "below ... health" (strict), the client brief says "current health
   <= threshold".  S4 pins INCLUSIVE.  The completion should also
   decide the evaluation instant: the engine evaluates the threshold
   AFTER the event's own damage (Syndra semantics), so the zap's
   10..27.35 + 3% AP damage counts toward crossing the threshold.
   The notes add: the uncharged zap does NOT execute shielded or
   invulnerable enemies below the threshold - a named boundary the
   engine's current seam cannot express (shield semantics); flag if
   the completion needs it.
4. TARGET-DEPENDENT RATIO vs ABSOLUTE: if the completion converts to a
   ratio at parse time, the parse needs target_max_health (available
   in ctx.target today); with a 0/absent target max health the
   conversion must fail closed (no execute), not divide by zero.  The
   API surface should display the ABSOLUTE threshold (the Asol-E
   precedent: "Executes below 7.6% max HP (152 HP)" carries the
   absolute number).
5. THE ZAP DAMAGE ROW (10..27.35 + 3% AP) is declared NOWHERE in the
   packet (base row is twenty zeros).  This matrix pins ONLY the
   execute range; whether the completion also prices the zap's damage
   (and how the zap ties to the auto-attack model - Zeri's Q replaces
   her basic attack) is out of this slice's pins; the current
   zero-damage passive and the full-charge ratio misattribution are
   pinned in S1/S5 so the coordinator can see the exact current
   declaration.
6. STALE P SOURCE REVISION: the module SOURCES pin the P ability entry
   at revision 3380499 (2022-01-07) while the parent entry is 4019486
   (2026-05-17); the cached notes claim testing on patch 26.12.  The
   per-ability revision should be re-pulled on the next patch day; the
   threshold row itself is current (70..170.59 matches the client
   brief).
7. NO ATOM ROOT EXISTS for the threshold: the binary atom catalog has
   only execute RULE flags (ZeriQ/ZeriQMis) and the flat 0.0
   basic-attack atom; the 70..170.59 + 20% AP numbers live only in the
   wiki JSON with empty units.  The completion's certification (S7
   xfail) must name the wiki row (data/champions.json "Zeri" P
   effects[1] "Bonus Damage") as its root and document that the binary
   carries no DataValues - or add a typed constant block with the
   receipt, mirroring the Asol _StardustRule pattern.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.atomizer import hash_domain_file
from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.champions.slotlib import extract_named
from src.calculator.champions.zeri import MODULE_COVERAGE, PACKET_SHA256
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_ZERI_DATA = _CHAMPION_DATA["Zeri"]
_P_ABILITY = _ZERI_DATA["abilities"]["P"][0]
_P_ATOMS = json.loads(Path("data/atoms/champions.json").read_text(encoding="utf-8"))[
    "objects"
]["Zeri"]
_MANIFEST_CHAMPIONS = json.loads(
    Path("data/atoms/manifest.json").read_text(encoding="utf-8")
)["domains"]["champions"]
_PACKET_ZERI = json.loads(
    Path("static/reviewed-packets.json").read_text(encoding="utf-8")
)["champions"]["Zeri"]
_PACKET_PATH = Path("static/reviewed-packets.json")

_AWAIT = "awaiting P4-Zeri-P ..."
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVELS = (1, 6, 11, 18, 20)
_REF_MAX_HP = 2358.0  # the level-18 reference target (Ahri, no items)

# The cached 20-value leveling rows (levels 1..20, indexed level-1).
_ZAP_ROW = [
    10,
    10.64,
    11.3,
    12,
    12.73,
    13.49,
    14.28,
    15.1,
    15.95,
    16.83,
    17.74,
    18.69,
    19.66,
    20.67,
    21.7,
    22.77,
    23.87,
    25,
    26.16,
    27.35,
]
_THRESHOLD_ROW = [
    70,
    75.29,
    80.59,
    85.88,
    91.18,
    96.47,
    101.76,
    107.06,
    112.35,
    117.65,
    122.94,
    128.24,
    133.53,
    138.82,
    144.12,
    149.41,
    154.71,
    160,
    165.29,
    170.59,
]
_FULL_BASE_ROW = [
    75,
    80,
    85,
    90,
    95,
    100,
    105,
    110,
    115,
    120,
    125,
    130,
    135,
    140,
    145,
    150,
    155,
    160,
    165,
    170,
]
_FULL_MAXHP_ROW = [
    1,
    1.59,
    2.18,
    2.76,
    3.35,
    3.94,
    4.53,
    5.12,
    5.71,
    6.29,
    6.88,
    7.47,
    8.06,
    8.65,
    9.24,
    9.82,
    10.41,
    11,
    11.59,
    12.18,
]
_AP_RATIO = 0.20


def _threshold(level: int, ap: float = 0.0) -> float:
    """The pinned execute threshold at *level* with *ap* ability power,
    recomputed from the cached row (the single source of truth)."""
    return _THRESHOLD_ROW[level - 1] + _AP_RATIO * ap


def _stats(level: int = 18, ap: float = 0.0) -> dict:
    return {
        "attack_damage": 90.0,
        "ability_power": ap,
        "base_attack_damage": 90.0,
        "bonus_attack_damage": 0.0,
        "attack_speed": 0.625,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 1015.0,
        "resource_regen_per_second": 0.0,
        "level": level,
    }


def _parse(
    level: int = 18,
    ap: float = 0.0,
    ranks: dict | None = None,
    target_max: float = _REF_MAX_HP,
):
    stats = _stats(level, ap)
    return stats, parse_champion_abilities(
        get_champion("Zeri"),
        level,
        ap,
        ability_ranks=ranks if ranks is not None else dict(_RANKS),
        champion_stats=stats,
        target_stats={"target_max_health": target_max},
        champion_options={},
    )


def _fight(
    *,
    level: int = 18,
    ap: float = 0.0,
    ranks: dict | None = None,
    target_health: float = _REF_MAX_HP,
    duration: float = 5.0,
    one_rotation: bool = True,
    score_only: bool = False,
    mr: float = 0.0,
    auto_attack_uptime: float = 0.0,
) -> dict:
    stats, abilities = _parse(level, ap, ranks=ranks, target_max=target_health)
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=target_health,
            target_armor=0.0,
            target_magic_resistance=mr,
            fight_duration_seconds=duration,
            auto_attack_uptime=auto_attack_uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
        ),
        score_only=score_only,
        champion_options={},
    )


def _api(champion_options: dict | None = None):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Zeri",
            "level": 18,
            "items": [],
            "role": "top",
            "ability_ranks": _RANKS,
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "target_health": _REF_MAX_HP,
            "target_armor": 50,
            "target_mr": 52,
            "champion_options": champion_options or {},
        },
    )


def _leveling(ability: dict, attribute: str) -> dict:
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"no leveling {attribute!r} in {ability.get('name')}")


def _atom(atom_id: str, name: str | None = None) -> dict:
    matches = [
        atom
        for atom in _P_ATOMS
        if atom["atom_id"] == atom_id and (name is None or atom.get("name") == name)
    ]
    assert len(matches) == 1, f"atom {atom_id!r} name={name!r}: {len(matches)}"
    return matches[0]


def _packet_sha256(packet: dict) -> str:
    payload = json.dumps(
        packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# S1 - Source evidence (three P effects, notes, leveling rows, atoms,
#      module declaration)
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_all_three_p_effects_verbatim(self):
        # The full cached P packet the execute-range contract is built
        # from: [0] charge prose (leveling EMPTY), [1] the UNCHARGED zap
        # with the execute threshold, [2] the FULL-CHARGE attack (named
        # out-of-scope boundary).
        descriptions = [fx["description"] for fx in _P_ABILITY["effects"]]
        assert descriptions == [
            "Innate: Zeri generates 1 charge for every 40 units she travels "
            "by any means and 10 charge every time she casts Burst Fire, up "
            "to a maximum of 100 charge. Her basic attacks consume charge to "
            "deal modified damage.Zeri gains maximum charge when the game "
            "starts and upon respawning.",
            "Basic Attack: Zeri zaps the target, dealing 10 : 27.35 (based "
            "on level) (+ 3% AP) magic damage, applying spell effects as "
            "spell damage, triggering on-cast effects and executing the "
            "target if they are below 70 : 170.59 (based on level) (+ 20% "
            "AP) health. This cannot critically strike and does not apply "
            "nor trigger on-hit and on-attack effects.",
            "At full charge, Zeri's next attack is empowered to consume all "
            "charge to deal 75 : 170 (based on level) (+ 110% AP) (+ 1% : "
            "12.18% (based on level) of target's maximum health) magic "
            "damage. The damage based on the target's health ratio is capped "
            "at 300 against monsters.",
        ]

    def test_p_notes_verbatim(self):
        # The notes carry the execute-range semantics the seam must honor:
        # the uncharged zap does NOT execute shielded/invulnerable enemies
        # below the threshold, and the Last Hit Indicator shows the
        # threshold.  (Shield/invulnerability exclusion is a named boundary
        # the engine's ratio seam cannot express today - AMBIGUITY 3.)
        assert _P_ABILITY["notes"] == (
            "Charged attacks only deal the base damage to  structures.\n"
            "Uncharged attacks do not execute enemies that are  shielded or "
            " invulnerable while below the health threshold.\n Spell shield "
            "will only block a fully charged attack. Uncharged attacks are "
            "not blocked.\nThe attack's range is affected by attack range "
            "modifiers ( Rapid Firecannon) (tested on patch 26.12).\n"
            "Uncharged and charged attacks trigger  Tear of the Goddess' "
            "Mana Charge and  Manaflow Band.\nAttacking a turret does not consume Crystalline "
            "Overgrowth.\nThe empowered attack will trigger but not be "
            "consumed against  wards or jungle plants.\nIf Last Hit "
            "Indicator enabled, it will indicate Living Battery's  execute "
            "threshold instead of its usual function."
        )

    def test_charge_effect_zero_has_no_leveling(self):
        assert _P_ABILITY["effects"][0]["leveling"] == []

    def test_uncharged_zap_leveling_rows(self):
        # effects[1]: the zap-damage row (10..27.35, DEGRADED: all units
        # empty) and the EXECUTE-THRESHOLD row named "Bonus Damage"
        # (70..170.59 with all-empty units + the [20.0] "% AP" modifier
        # whose unit survived the parse).
        leveling = _P_ABILITY["effects"][1]["leveling"]
        by_name = {row["attribute"]: row for row in leveling}
        zap = by_name["Per-Level Scaling"]
        assert zap["modifiers"][0]["values"] == _ZAP_ROW
        assert zap["modifiers"][0]["units"] == [""] * 20
        threshold = by_name["Bonus Damage"]
        assert threshold["modifiers"][0]["values"] == _THRESHOLD_ROW
        assert threshold["modifiers"][0]["units"] == [""] * 20
        assert threshold["modifiers"][1]["values"] == [20.0]
        assert threshold["modifiers"][1]["units"] == ["% AP"]

    def test_full_charge_leveling_rows(self):
        # effects[2]: the full-charge boundary's rows (75..170 base +
        # 1%..12.18% max HP) - pinned so the completion can never confuse
        # them with the uncharged threshold row.
        leveling = _P_ABILITY["effects"][2]["leveling"]
        by_name = {row["attribute"]: row for row in leveling}
        assert by_name["Per-Level Scaling"]["modifiers"][0]["values"] == (
            _FULL_BASE_ROW
        )
        assert by_name["Max Health Damage"]["modifiers"][0]["values"] == (
            _FULL_MAXHP_ROW
        )
        assert by_name["Max Health Damage"]["modifiers"][0]["units"] == ["%"] * 20

    def test_p_metadata_fields(self):
        assert _P_ABILITY["damageType"] == "MAGIC_DAMAGE"
        assert _P_ABILITY["targeting"] == "Unit"
        assert _P_ABILITY["resource"] == "CHARGE"
        assert _P_ABILITY["cost"]["modifiers"][0]["values"] == [0, 0, 0]
        assert _P_ABILITY["cost"]["modifiers"][0]["units"] == ["10 \u2022 100"] * 3

    def test_module_declaration_p_packet_slot(self):
        # The module's P declaration (static/reviewed-packets.json): a
        # zero-base "packet" slot whose ONLY ratio row is the full-charge
        # %maxHP curve (misattributed) and whose base row is twenty zeros
        # (the zap row 10..27.35 is NOT declared).  This is the exact
        # declaration the completion extends with the execute-range seam.
        spec = _PACKET_ZERI["slots"]["P"]
        assert spec["kind"] == "packet"
        assert spec["name"] == "Living Battery"
        assert spec["cooldown"] == 0.0
        assert spec["damage_type"] == "magic"
        assert spec["ranks"] == "level"
        assert spec["source"] == ["P", 0]
        assert spec["base"] == [0.0] * 20
        # The ratio row is the full-charge %maxHP curve in FRACTION form
        # (0.01 == the wiki's 1%) - the misattribution is exact.
        assert spec["ratios"] == [
            {"stat": "targetMaxHp", "values": [v / 100.0 for v in _FULL_MAXHP_ROW]}
        ]

    def test_module_packet_hash_pins_manifest_digest(self):
        # The module's PACKET_SHA256 is the canonical digest of the Zeri
        # packet manifest entry - drift in either file trips this.
        assert (
            PACKET_SHA256
            == "f03ac495eb30baef9672e60deb2f448b0da551e22e39c3113cbc0cfee9e1c055"
        )
        assert _packet_sha256(_PACKET_ZERI) == PACKET_SHA256

    def test_module_meta_declares_no_options(self):
        meta = get_champion_options_meta("Zeri")
        assert meta["options"] == []
        assert MODULE_COVERAGE["P"] == "modeled"
        assert any("no-damage slot" in text for text in meta["assumptions"])

    def test_parse_emits_zero_damage_passive_at_every_level(self):
        # The P4 completion: the parse emits the Living Battery on-hit
        # entry at every level — the zap's on_hit payload + the execute
        # stamp (the threshold ratio + the source) with the typed
        # certification surface; the detail names the boundary.
        for level in _LEVELS:
            _, abilities = _parse(level, 0.0)
            passive = abilities["passive"]
            assert passive["name"] == "Living Battery"
            assert passive["on_hit"]["name"] == "Living Battery (on-hit)"
            assert passive["on_hit"]["damage_type"] == "magic"
            assert passive["on_hit"]["damage_per_hit"] > 0.0
            assert passive["execute_threshold_ratio"] > 0.0
            assert passive["execute_source"] == "Living Battery"
            assert "Executes below" in passive["detail"]
            assert passive["certified_constants"]["threshold_level_1"] == 70.0

    def test_atoms_are_the_degraded_state(self):
        # The atom catalog (data/atoms/champions.json "Zeri") carries NO
        # threshold numbers: the passive has only a flat 0.0 basic-attack
        # atom, and the only damage.execute atoms are the Q-side rule
        # flags with timing/bitmask values.  The 70..170.59 + 20% AP
        # numbers exist ONLY in the wiki JSON (degraded: units empty).
        assert _atom("damage.basic-attack", "ZeriPassive")["values"] == [0.0]
        assert _atom("damage.basic-attack", "ZeriPassive")["units"] == ["flat"]
        q_execute = _atom("damage.execute", "ZeriQ")
        assert q_execute["values"] == [0.0, 0.0, 25000.0, 6154.0]
        assert _atom("damage.execute", "ZeriQMis")["values"] == [
            0.0,
            0.0,
            25000.0,
            6154.0,
        ]
        execute_atoms = [
            atom for atom in _P_ATOMS if atom["atom_id"] == "damage.execute"
        ]
        assert [atom["name"] for atom in execute_atoms] == ["ZeriQ", "ZeriQMis"]
        # No threshold numbers anywhere in the passive/execute atoms (the
        # 70.0 that appears elsewhere in the catalog is ZeriR's cast
        # radius - unrelated to the execute threshold).
        for atom in execute_atoms + [_atom("damage.basic-attack", "ZeriPassive")]:
            for value in atom.get("values", []):
                assert value not in (70.0, 170.59, 20.0)


# ---------------------------------------------------------------------------
# S2 - Level endpoints + middle (the 70..170.59 curve, indexed by level)
# ---------------------------------------------------------------------------


class TestThresholdCurve:
    def test_row_is_the_full_twenty_level_curve(self):
        # The row has 20 values == the level cap: level 1 = 70,
        # level 20 = 170.59.  There is no separate 4-value row in the
        # cache (the parent brief's "4 values" were the first four
        # entries of the 20-value row).
        assert len(_THRESHOLD_ROW) == 20
        assert _THRESHOLD_ROW[0] == 70
        assert _THRESHOLD_ROW[-1] == 170.59

    def test_threshold_values_at_endpoints_and_middle(self):
        # The pinned curve: level 1/6/11/18/20 -> 70/96.47/122.94/160/
        # 170.59 at 0 AP (the client brief's "70 to 170.59 by level").
        expected = {1: 70, 6: 96.47, 11: 122.94, 18: 160, 20: 170.59}
        for level, want in expected.items():
            assert _threshold(level) == pytest.approx(want)
            assert _THRESHOLD_ROW[level - 1] == pytest.approx(want)

    def test_engine_extractor_resolves_the_degraded_row(self):
        # The degraded row (empty units) resolves as FLAT through the
        # engine's own extractor - exactly row[level-1] + 20% AP, never a
        # zero fallback.  This is the resolution the completion's module
        # can rely on ("Bonus Damage" attribute, rank == level).
        stats = _stats(18, 0.0)
        for level in _LEVELS:
            resolved = extract_named(
                _P_ABILITY,
                "Bonus Damage",
                level,
                stats,
                {"target_max_health": _REF_MAX_HP},
            )
            assert resolved == pytest.approx(_threshold(level))

    def test_parse_entry_exposes_threshold_at_every_level(self):
        # The smallest contract: whichever typed seam lands (ratio
        # conversion or absolute key - AMBIGUITY 2), the passive entry's
        # threshold VALUE must equal the row at each level, and the
        # source must be named.
        for level in _LEVELS:
            _, abilities = _parse(level, 0.0)
            entry = abilities["passive"]
            # The seam carries the ratio (threshold / target max health);
            # the flat value is recovered by the reference max HP.
            value = float(entry.get("execute_threshold_ratio", 0.0) or 0.0)
            assert value * _REF_MAX_HP == pytest.approx(_threshold(level))
            assert entry.get("execute_source") == "Living Battery"


# ---------------------------------------------------------------------------
# S3 - AP 0 / nonzero (the 20% AP term)
# ---------------------------------------------------------------------------


class TestApTerm:
    def test_ap_term_resolves_from_the_degraded_row(self):
        # The "% AP" modifier survived the half-parse, so the engine
        # extractor prices the 20% AP term: +20 at 100 AP, +100 at 500.
        stats = _stats(18, 100.0)
        assert extract_named(_P_ABILITY, "Bonus Damage", 1, stats, {}) == pytest.approx(
            90.0
        )  # 70 + 20
        assert extract_named(
            _P_ABILITY, "Bonus Damage", 18, stats, {}
        ) == pytest.approx(
            180.0
        )  # 160 + 20
        stats500 = _stats(18, 500.0)
        assert extract_named(
            _P_ABILITY, "Bonus Damage", 18, stats500, {}
        ) == pytest.approx(
            260.0
        )  # 160 + 100
        assert extract_named(
            _P_ABILITY, "Bonus Damage", 20, stats500, {}
        ) == pytest.approx(
            270.59
        )  # 170.59 + 100

    def test_threshold_helper_prices_ap(self):
        assert _threshold(1, 100.0) == pytest.approx(90.0)
        assert _threshold(6, 500.0) == pytest.approx(196.47)
        assert _threshold(11, 100.0) == pytest.approx(142.94)
        assert _threshold(18, 500.0) == pytest.approx(260.0)
        assert _threshold(20, 100.0) == pytest.approx(190.59)

    def test_parse_entry_exposes_ap_term(self):
        _, abilities = _parse(18, 100.0)
        entry = abilities["passive"]
        value = float(entry.get("execute_threshold_ratio", 0.0) or 0.0)
        assert value * _REF_MAX_HP == pytest.approx(180.0)
        _, abilities500 = _parse(18, 500.0)
        value500 = float(
            abilities500["passive"].get("execute_threshold_ratio", 0.0) or 0.0
        )
        assert value500 * _REF_MAX_HP == pytest.approx(260.0)


# ---------------------------------------------------------------------------
# S4 - Target health below / equal / above the threshold (equality)
# ---------------------------------------------------------------------------


class TestExecuteSemantics:
    """Ranks all 0: the ONLY slot in the fight is the passive (zero damage
    today), so ``target_ending_health == 0`` can only come from the
    execute - a clean isolation for the contract."""

    def test_executes_below_threshold(self):
        result = _fight(
            level=18,
            ap=0.0,
            ranks={k: 0 for k in "QWER"},
            target_health=159.99,
            auto_attack_uptime=1.0,
            duration=2.0,
        )
        assert result["target_ending_health"] == 0.0

    def test_executes_at_exact_threshold_equality(self):
        result = _fight(
            level=18,
            ap=0.0,
            ranks={k: 0 for k in "QWER"},
            target_health=160.0,
            auto_attack_uptime=1.0,
            duration=2.0,
        )
        assert result["target_ending_health"] == 0.0

    def test_survives_above_threshold_today(self):
        # This half of the equality contract ALREADY holds: with no
        # execute seam, a target at 160.01 (> threshold 160) survives
        # untouched (no damage priced, no execute).  Post-completion the
        # seam must keep it: above the threshold the zap never executes.
        result = _fight(
            level=18, ap=0.0, ranks={k: 0 for k in "QWER"}, target_health=160.01
        )
        assert result["target_ending_health"] == pytest.approx(160.01)

    def test_zap_damage_counts_toward_threshold(self):
        # Level 18, AP 0, MR 0: the zap is 25 magic damage; a target at
        # 180 enters the zap at 180, takes 25, lands at 155 <= 160 and is
        # executed.  (Post-completion the zap's damage must be priced for
        # this to hold; if the completion prices only the threshold, this
        # pin documents the interaction for the coordinator.)
        result = _fight(
            level=18,
            ap=0.0,
            ranks={k: 0 for k in "QWER"},
            target_health=180.0,
            auto_attack_uptime=1.0,
            duration=2.0,
        )
        assert result["target_ending_health"] == 0.0


# ---------------------------------------------------------------------------
# S5 - Uncharged vs full-charge boundary
# ---------------------------------------------------------------------------


class TestUnchargedVsFullCharge:
    def test_full_charge_is_the_named_out_of_scope_boundary(self):
        # effects[2] is the full-charge attack: 75..170 + 110% AP +
        # 1%..12.18% max HP, monster cap 300 - a SEPARATE effect from the
        # uncharged zap's execute threshold (effects[1]).
        full = _P_ABILITY["effects"][2]["description"]
        assert "At full charge" in full
        assert "75 : 170 (based on level)" in full
        assert "110% AP" in full
        assert "1% : 12.18%" in full
        assert "capped at 300 against monsters" in full

    def test_current_packet_misattributes_full_charge_ratio(self):
        # The module's P packet declares base zeros + the FULL-CHARGE
        # %maxHP curve as its only ratio - the zap row and the execute
        # threshold are undeclared.  This is the exact current state the
        # completion extends; the full-charge ratio must not leak into
        # the execute seam.
        spec = _PACKET_ZERI["slots"]["P"]
        assert spec["base"] == [0.0] * 20
        assert spec["ratios"][0]["values"] == [v / 100.0 for v in _FULL_MAXHP_ROW]
        assert spec["ratios"][0]["stat"] == "targetMaxHp"

    def test_current_fight_prices_no_passive_damage(self):
        # The API/engine fight today: no passive breakdown row, and the
        # total equals exactly the Q+W+E+R sum (the misattributed
        # full-charge ratio is dead - total_raw 0 drops the row).
        body = _api({}).get_json()
        assert {"Q", "W", "E", "R", "auto_attacks", "on_hit_ability_passive"} <= set(
            body["breakdown"].keys()
        )
        row_total = sum(row["total_damage"] for row in body["breakdown"].values())
        # Per-row one-decimal rounding can drift the sum by 0.1 vs the
        # rounded total; the point is no passive row contributes.
        assert body["total_damage"] == pytest.approx(row_total, abs=0.2)

    def test_full_charge_ratio_stays_unpriced_today(self):
        # The full-charge term (75..170 + 110% AP + 1%..12.18% max HP) is
        # the named out-of-scope boundary and ALREADY unpriced: the
        # passive entry carries total_raw 0.0 (the misattributed ratio is
        # dead) and no detail references the full-charge 110% AP.  This
        # guard stays live through the completion - the execute-range
        # seam must never re-price the full-charge attack.
        stats, abilities = _parse(18, 0.0)
        entry = abilities["passive"]
        assert entry["total_raw"] == 0.0
        detail = str(entry.get("detail", ""))
        assert "110% AP" not in detail


# ---------------------------------------------------------------------------
# S6 - Malformed / stale / ambiguous declarations fail closed
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_degraded_row_resolves_exactly_not_zero(self):
        # The half-parsed row (values survive, units empty) must resolve
        # to the exact threshold - never a stale-literal fallback and
        # never a silent zero (the Statikk-Shiv failure mode).
        stats = _stats(18, 0.0)
        assert extract_named(
            _P_ABILITY, "Bonus Damage", 18, stats, {}
        ) == pytest.approx(160.0)
        # The zap-damage row is equally resolvable (pinned as evidence;
        # its pricing is out of this slice's pins - AMBIGUITY 5).
        assert extract_named(
            _P_ABILITY, "Per-Level Scaling", 18, stats, {}
        ) == pytest.approx(25.0)

    def test_no_atom_can_go_stale_for_the_threshold(self):
        # There is no atom root for the threshold numbers - the only
        # execute atoms carry timing/bitmask values, so a patch that
        # changes the threshold cannot be caught by atom drift; the
        # wiki row is the sole root (pinned in S7's xfail).
        for atom in _P_ATOMS:
            if atom["atom_id"] == "damage.execute":
                assert atom["values"] == [0.0, 0.0, 25000.0, 6154.0]
                assert 70.0 not in atom["values"]
                assert 170.59 not in atom["values"]

    def test_unknown_champion_option_rejected_400(self):
        # Zeri declares NO options; any champion_options key is unknown
        # and must fail closed with a named 400 (the Asol convention).
        response = _api({"execute_range_bonus": 1})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options contains unknown option execute_range_bonus"
        )

    def test_passive_prices_zero_damage_at_every_level_today(self):
        for level in range(1, 21):
            _, abilities = _parse(level, 0.0)
            assert abilities["passive"]["total_raw"] == 0.0

    def test_level_cap_row_length_supports_level_twenty(self):
        # Level cap is 20 and the row has 20 values: rank == level, so
        # index min(level, 20) - 1; level 20 resolves the last value and
        # never overruns.
        stats = _stats(20, 0.0)
        assert extract_named(
            _P_ABILITY, "Bonus Damage", 20, stats, {}
        ) == pytest.approx(170.59)
        stats1 = _stats(1, 0.0)
        assert extract_named(
            _P_ABILITY, "Bonus Damage", 1, stats1, {}
        ) == pytest.approx(70.0)

    def test_stale_p_source_revision_is_pinned(self):
        # The module SOURCES pin the P ability entry to revision 3380499
        # (2022-01-07) - years older than the parent entry (4019486,
        # 2026-05-17) and the patch-26.12-tested notes.  Pinned so the
        # patch-day audit trips on the stale per-ability revision
        # (AMBIGUITY 6).
        meta = get_champion_options_meta("Zeri")
        sources = {row["label"]: row for row in meta["sources"]}
        parent = sources["Zeri parent entry"]
        assert parent["revision_id"] == 4019486
        assert parent["revision_timestamp"] == "2026-05-17T18:52:39Z"
        p_entry = sources["Zeri P ability entry"]
        assert p_entry["revision_id"] == 3380499
        assert p_entry["revision_timestamp"] == "2022-01-07T16:38:00Z"


# ---------------------------------------------------------------------------
# S7 - Atom / source receipts
# ---------------------------------------------------------------------------


class TestSourceAndAtomReceipts:
    def test_atom_hashes_are_stable(self):
        # The Zeri champion-domain atoms (data/atoms/champions.json):
        # the passive's flat basic-attack atom and the Q-side execute
        # rule flags.  Hashes are pinned so a re-atomization that touches
        # Zeri trips these (fail-closed staleness).
        assert _atom("damage.basic-attack", "ZeriPassive")["hash"] == "288e9c6b195123cb"
        assert _atom("damage.execute", "ZeriQ")["hash"] == "6013648e7780edb2"
        assert _atom("damage.execute", "ZeriQMis")["hash"] == "3a119ecc1dcad01d"

    def test_manifest_receipt_matches_the_cached_file(self):
        # The champions-domain receipt: the manifest's source_ref hashes
        # to the actual data/champions.json on disk (computed here), and
        # the domain digest is verified against a RECOMPUTED content-stable
        # hash of the on-disk champions atom file (atomizer.hash_domain_file)
        # rather than a literal — stronger than a literal because it checks
        # the actual bytes every run and survives legitimate re-atomization.
        assert _MANIFEST_CHAMPIONS["object_count"] == 173
        assert _MANIFEST_CHAMPIONS["sha256"] == hash_domain_file(
            Path("data/atoms/champions.json")
        )
        actual = hashlib.sha256(Path("data/champions.json").read_bytes()).hexdigest()
        assert _MANIFEST_CHAMPIONS["source_ref"].endswith(
            f"data/champions.json@sha256:{actual[:16]};data/bin/characters"
        )

    def test_packet_spec_receipt_is_the_module_hash(self):
        # The static/reviewed-packets.json Zeri entry digests to the
        # module's pinned PACKET_SHA256 (S1 cross-check).
        assert _packet_sha256(_PACKET_ZERI) == PACKET_SHA256

    def test_module_sources_pin_wiki_revisions(self):
        meta = get_champion_options_meta("Zeri")
        sources = {row["label"]: row for row in meta["sources"]}
        assert sources["Zeri parent entry"]["url"] == (
            "https://wiki.leagueoflegends.com/en-us/Zeri"
        )
        assert sources["Zeri P ability entry"]["url"] == (
            "https://wiki.leagueoflegends.com/en-us/Template:Data_Zeri/I"
        )
        assert len(meta["sources"]) == 6  # parent + P/Q/W/E/R entries

    def test_typed_atom_backed_certification(self):
        # Mirror the Asol _StardustRule pattern: a typed rule with a
        # public receipt and an atom_ids surface for the threshold
        # (per-level values + 20% AP), whose hashes trip on data drift.
        from src.calculator.champions.zeri import ZERI_P_EXECUTE_RULE  # noqa: F401

        receipt = ZERI_P_EXECUTE_RULE.public_receipt()
        assert receipt["threshold_level_1"] == pytest.approx(70.0)
        assert receipt["threshold_level_20"] == pytest.approx(170.59)
        assert receipt["ap_ratio"] == pytest.approx(0.20)
        assert receipt["source"]["wiki"]["revision_id"] == 4019486
        assert ZERI_P_EXECUTE_RULE.public_receipt()[
            "atom_ids"
        ]  # typed certification surface


# ---------------------------------------------------------------------------
# S8 - API output (/api/calculate execute surface)
# ---------------------------------------------------------------------------


class TestApiOutput:
    def test_api_baseline_200_with_no_execute_surface(self):
        # TODAY: 200, no execute* keys anywhere, no passive breakdown
        # row, and no stamped damage events - the fail-closed absence.
        response = _api({})
        assert response.status_code == 200
        body = response.get_json()
        assert body["breakdown"].keys() >= {
            "Q",
            "W",
            "E",
            "R",
            "auto_attacks",
            "on_hit_ability_passive",
        }
        for event in body.get("damage_events", []):
            assert "execute_threshold_ratio" not in event
            assert "execute_source" not in event

    def test_api_carries_the_p_execute_surface(self):
        response = _api({})
        assert response.status_code == 200
        body = response.get_json()
        # The on-hit convention: the passive's per-auto payload rides
        # the on_hit_ability_passive row (Quinn/Riven precedent).
        row = body["breakdown"].get("on_hit_ability_passive")
        assert row is not None, "P on-hit row absent"
        assert row["name"] == "Living Battery (on-hit)"
        assert row["count"] > 0
        assert row["damage_per_hit"] > 0.0
        # The execute surface lives on the parse entry + the fight's
        # ending health (the threshold 160 at level 18, AP 0).
        assert body["target_ending_health"] >= 0.0


# ---------------------------------------------------------------------------
# S9 - Score/receipt parity (full vs score_only byte-identical)
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_full_vs_score_only_byte_identical_one_rotation(self):
        # PASSES today (no P surface to diverge); the completion must
        # keep the scored fast path byte-identical on the scored surface.
        full = _fight(level=18, ap=0.0, one_rotation=True)
        scored = _fight(level=18, ap=0.0, one_rotation=True, score_only=True)
        assert full["breakdown"] == scored["breakdown"]
        assert full["total_damage"] == scored["total_damage"]
        assert full["resource_spent"] == scored["resource_spent"]
        assert full["resource_remaining"] == scored["resource_remaining"]
        assert full["resource_ledger"] == scored["resource_ledger"]
        assert full["notes"] == scored["notes"]
        shared = ("time", "slot", "name", "ordinal", "resource_cost")
        assert len(full["cast_timeline"]) == len(scored["cast_timeline"])
        for full_row, scored_row in zip(full["cast_timeline"], scored["cast_timeline"]):
            assert {k: full_row[k] for k in shared} == {
                k: scored_row[k] for k in shared
            }

    def test_full_vs_score_only_byte_identical_ap_nonzero(self):
        full = _fight(level=18, ap=500.0, one_rotation=True)
        scored = _fight(level=18, ap=500.0, one_rotation=True, score_only=True)
        assert full["breakdown"] == scored["breakdown"]
        assert full["total_damage"] == scored["total_damage"]

    def test_timed_fight_score_parity(self):
        full = _fight(level=18, ap=0.0, one_rotation=False, duration=10.0)
        scored = _fight(
            level=18, ap=0.0, one_rotation=False, duration=10.0, score_only=True
        )
        assert full["total_damage"] == scored["total_damage"]
        assert full["resource_ledger"] == scored["resource_ledger"]


# ---------------------------------------------------------------------------
# S10 - Regression surface (kept green; run list)
# ---------------------------------------------------------------------------


class TestRegressionSurface:
    def test_zeri_grep_surface_is_pinned(self):
        # Every tests/ file mentioning "zeri" (case-insensitive): adding
        # a new Zeri test file must extend this pin, and every listed
        # file must stay green in the sanity run.
        test_dir = Path("tests")
        hits = sorted(
            path.name
            for path in test_dir.glob("test_*.py")
            if "zeri" in path.read_text(encoding="utf-8", errors="ignore").lower()
        )
        assert hits == [
            "test_cp10_batch_10.py",
            "test_e2_dot_3.py",
            "test_e5_fix_2.py",
            # Mel's P test cites Zeri's Living Battery as the contrast
            # case for why Overwhelm's kill boundary is NOT modeled as
            # an execute ratio; it asserts nothing about Zeri herself.
            "test_mel_searing_brilliance.py",
            "test_spellblade_on_hit_matrix.py",
            "test_zeri_p_execute_range.py",
        ]

    def test_module_meta_pins_unchanged(self):
        meta = get_champion_options_meta("Zeri")
        assert meta["options"] == []
        assert any("Burst Fire" in text for text in meta["assumptions"])
        assert any("Passive plus Q/W/E/R" in text for text in meta["assumptions"])
        assert MODULE_COVERAGE["P"] == "modeled"
        assert MODULE_COVERAGE["Q"] == "modeled"
        assert MODULE_COVERAGE["R"] == "modeled"


# ---------------------------------------------------------------------------
# Sanity run list (contract 10) - run ONLY this file plus:
#   .venv/bin/python -m pytest tests/test_zeri_p_execute_range.py \
#     tests/test_yasuo_yone_q3_crit.py tests/test_aurelion_sol_stardust.py \
#     tests/test_senna_relic_cannon.py tests/test_quinn_p_crit.py \
#     tests/test_mana_restore_refund.py tests/test_ezreal_w_mark_refund.py \
#     tests/test_jayce_w_mana_restore.py tests/test_resource_ledger*.py \
#     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#     tests/test_champion_options.py tests/test_app.py
# Existing Zeri regression files (the S10 grep pin), run separately:
#   tests/test_spellblade_on_hit_matrix.py tests/test_e5_fix_2.py \
#   tests/test_cp10_batch_10.py tests/test_e2_dot_3.py
