"""P4 Jayce — mid-fight form transitions (test-matrix owner: RLM-2 C).

Focused TDD matrix for Jayce's form-transition contract, DISJOINT from
``tests/test_jayce.py`` and ``tests/test_jayce_w_mana_restore.py`` (every
test here is named ``test_p4j_*``).  It pins the CURRENT one-stance
runtime end-to-end (source evidence, parse parity, defaults, cooldown
boundaries, zero-auto, score parity, unchanged boundaries) and pins the
coordinator's form-transition CONTRACT, which has NOT landed: the
genuinely-absent transition behavior is ``xfail(strict=True)`` with reason
``awaiting P4-Jayce-Form ...``.  The completion removes the markers and
reconciles any pin it disagrees with.

CURRENT RUNTIME FACTS (verify-before-pin completed against
``src/calculator/champions/jayce.py``, ``src/calculator/damage.py``,
``data/champions.json`` and ``data/atoms/abilities.json``):

- ``jayce.py`` ships the ONE-STANCE model: ``hammer_stance`` bool
  (default False = Cannon) dispatches every basic slot — Q/W/E store
  [0] = Hammer, [1] = Cannon and ``_transform_ability`` resolves R BY
  NAME (the R JSON order is INVERTED: [0] = Cannon, [1] = Hammer).
  ``CAST_ORDER = ["R", "Q", "Q2", "W", "E"]`` (Jayce transforms BEFORE
  casting; the engine default puts R last).
- R has ENTIRELY EMPTY ``leveling`` arrays in both JSON entries (all
  numbers are module constants sourced from the live game files — the
  Community Dragon ``jayce.bin.json`` receipt is in the module
  docstring): R Hammer = armor/MR ``stat_buff`` (5/12/19/26 + 7.5% bonus
  AD) + ONE empowered magic auto (25/60/95/130 + 30% bonus AD); R Cannon
  = one armor/MR-shred ``target_debuff`` (20/25/30/35% for 5s) + an
  empowered auto with NO damage (the module does NOT stamp
  ``empowers_next_auto`` on the cannon R — the shred rides as a
  fight-wide debuff, time-weighted by its 5s window; the Kog'Maw rule
  keeps it from amplifying its own row).
- Transform binary evidence: BOTH cached R entries carry cooldown
  [6]*6 (``affectedByCdr``), ``castTime: "none"`` (no ``cast_time``
  parse key -> the engine's instant cast), cost/resource None (the
  parse emits ``resource_cost`` 0.0).  The engine casts R EXACTLY ONCE
  per timed fight (the single-cast rule, ``_schedule_shared_casts``),
  so the 6s cooldown never recasts in the current model.  In the
  engine's DEFAULT cast order R lands after E's 0.25s cast (hammer
  fights show R at t=0.25); the pipeline applies Jayce's declared order
  and R casts at t=0.
- P (Hextech Capacitor) is unmodeled: two byte-identical cached entries
  ("Hextech Capacitor" / "Hextech Capacitor 2" — a parser artifact),
  prose "Innate: Whenever Jayce switches between either Hammer Stance or
  Cannon Stance, he gains ghosting and 30 bonus movement speed for 0.75
  seconds.", ``timing.active_duration`` atom 0.75s.
- W mana restore rides BOTH stances (§4.58): 15-25 by W rank on every
  modeled basic attack (ordinary autos + in-window Hyper Charge swings),
  source "Jayce W passive (Mana Restored)", atom
  ``ability.mana _restored`` bfeb0d88945a263e.
- The cached R ``notes`` carry the form-transition evidence: "Both
  Transform on-hit effects have no set duration and will only be
  consumed when Jayce either lands a basic attack or switches stances."
  and "Transformations do not count as ability activations for the
  purposes of on-cast effects such as  Spellblade..." — the transform
  is a free, instant, spellblade-inert action whose on-hit persists
  until consumed.

THE ASSUMPTION the contract must not break (module ASSUMPTIONS):
"Jayce is modeled in ONE stance at a time — toggle hammer_stance to see
each form.  The cross-stance burst combo (gate -> supercharged Shock
Blast -> Transform -> empowered Hammer auto -> Thundering Blow -> To the
Skies!) is not modeled as a single rotation."

The coordinator's completion adds the SMALLEST evidence-backed
form-transition contract: a fail-closed EXPLICIT input (the fight cannot
prove a transition time/sequence), default byte-identical, no invented
transform duration/cooldown/state effect.

CONTRACT SEMANTICS PINNED HERE (MODEL B1 — flagged for the coordinator):
  - new input: ``transform_time`` FLOAT option, default 0.0 = no
    declared mid-fight transform (byte-identical default), validated
    finite and within (0, fight_duration]; label names the mid-fight
    transform.
  - the cast SCHEDULE is unchanged (the opening stance's cooldown grid:
    R@0 single cast, Q/W/E recasts at their opening-stance times).
  - a cast at time t prices with the OPENING stance's packet when
    t < T and with the FLIPPED stance's packet when t >= T (the
    boundary is at/after, per the brief).
  - R's cast is the transform: R@0 uses the opening stance's R packet
    (cannon shred / hammer empower); the declared T is the time of the
    SECOND transform, whose flipped-stance R packet's on-hit applies at
    T (hammer empower rides the first modeled auto at/after T; the
    cannon shred starts at T and follows the existing time-weighted
    5s-window rule).
  - the W per-auto restore keeps riding the modeled auto stream across
    the flip (amounts unchanged, auto_index continues, no reset at T).
  Every ambiguity in MODEL B1 is named in the section comments; the
  coordinator's actual completion wins and these pins are the ones to
  reconcile.

Contract map (parent's 11 rules -> tests):
  1  source evidence                      TestP4JSourceEvidence (S1)
  2  both-form parse parity               TestP4JParseParity (S2)
  3  default behavior                     TestP4JDefaultBehavior (S3)
  4  the transition contract              TestP4JTransitionContract (S4)
  5  cooldown/timing boundaries           TestP4JCooldownBoundaries (S5)
  6  one-rotation behavior                TestP4JOneRotation (S6)
  7  zero-auto behavior                   TestP4JZeroAuto (S7)
  8  API validation                       TestP4JApiValidation (S8)
  9  score/receipt parity                 TestP4JScoreParity (S9)
  10 unchanged boundaries                 TestP4JUnchangedBoundaries (S10)
  11 existing regression surface          TestP4JRegressionSurface (S11)

Expected values are recomputed from ``data/champions.json`` rows, the
live atomization and the module's own typed constants — no literal
damage constants beyond the sourced cooldowns and the reference build's
own stats.
"""

import copy
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.atomizer_domains import atomize_abilities
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_option_rotation,
    get_champion_options_meta,
    parse_champion_abilities,
    registered_champion_names,
)
from src.calculator.champions import jayce as jayce_module
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight

_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_PATH = _ROOT / "data" / "atoms" / "abilities.json"

CHAMPION = "Jayce"

# The FORM TRANSITION RECEIPT contract (P4): NO transition option is
# declared — the engine cannot host a mid-fight stance swap (the entries
# are consumed fight-wide: one packet per slot, one cooldown per slot,
# fight-wide stat_buffs, single-cast R at t=0), so the fail-closed gate
# is the API's unknown-option rejection of any transform_* spelling.
# The R cast IS the Transform and the fight plays entirely in the
# destination stance that hammer_stance selects; a cross-stance sequence
# is modeled as TWO one-stance fights (the ASSUMPTIONS receipt).
OPTION_KEY = "transform_time"  # deliberately NEVER declared

# Genuinely-absent mechanics are xfailed with this reason prefix; the
# completion removes the markers (strict) and reconciles the pins.
_AWAIT = "awaiting P4-Jayce-Form"

# ---------------------------------------------------------------------------
# Reference build (test_jayce.py's STATS_250_AD convention): level 18,
# Q/W/E rank 6 (R never leveled), 250 total AD / 150 bonus AD, 1.0 AS,
# 0 crit / 0 haste, 2500 max-HP target.  The direct-engine fights below
# use a 0-resist target so raw == mitigated and the pins are integers.
# ---------------------------------------------------------------------------

_STATS = {
    "ability_power": 0.0,
    "armor_penetration_bonus_percent": 0.0,
    "armor_penetration_percent": 0.0,
    "basic_ability_haste": 0.0,
    "bonus_health": 0.0,
    "bonus_mana": 0.0,
    "flat_armor_penetration": 0.0,
    "health": 0.0,
    "is_melee": True,
    "lethality": 0.0,
    "level": 1,
    "magic_penetration_flat": 0.0,
    "magic_penetration_percent": 0.0,
    "max_mana": 0.0,
    "move_speed": 0.0,
    "omnivamp_percent": 0.0,
    "resource_regen_per_second": 0.0,
    "ultimate_haste": 0.0,
    "attack_damage": 250.0,
    "base_attack_damage": 100.0,
    "bonus_attack_damage": 150.0,
    "attack_speed": 1.0,
    "attack_speed_ratio": 0.658,
    "bonus_attack_speed": 0.0,
    "critical_strike_chance": 0.0,
    "ability_haste": 0.0,
    "armor": 100.0,
    "magic_resistance": 50.0,
}
_TARGET = {"target_max_health": 2500.0}
_DURATION = 10.0
# Jayce's declared order (pipeline applies it; the direct engine takes it
# explicitly so R resolves first, exactly as the pipeline does).
_CAST_ORDER = ["R", "Q", "Q2", "W", "E"]

# Sourced R module constants at level 18 (tier index 3).
_HAMMER_RESISTS = 26.0 + 0.075 * 150.0  # 37.25
_HAMMER_AUTO = 130.0 + 0.30 * 150.0  # 175.0
_CANNON_SHRED = 35.0


def _json(result) -> str:
    """Deterministic fingerprint for byte-identity comparisons."""
    return json.dumps(result, sort_keys=True, default=lambda o: f"<{type(o).__name__}>")


def _parse(options=None):
    """Parse the reference build at level 18."""
    return parse_champion_abilities(
        get_champion(CHAMPION),
        18,
        0.0,
        champion_options=options,
        champion_stats=dict(_STATS),
        target_stats=dict(_TARGET),
    )


def _fight(
    options=None,
    *,
    duration=_DURATION,
    uptime=1.0,
    one_rotation=False,
    score_only=False,
    **overrides,
):
    """Direct-engine fight at the reference build, 0-resist target, with
    Jayce's declared cast order (the pipeline surface's order)."""
    config = {
        "target_health": 2500.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": duration,
        "auto_attack_uptime": uptime,
        "one_rotation": one_rotation,
        "deterministic": True,
        "cast_order": list(_CAST_ORDER),
    }
    config.update(overrides)
    return calculate_fight_damage(
        dict(_STATS),
        _parse(options),
        [],
        FightConfig(**config),
        score_only=score_only,
        champion_options=options,
    )


def _pipeline_fight(
    options=None,
    *,
    duration=_DURATION,
    uptime=1.0,
    one_rotation=False,
    score_only=False,
    **overrides,
):
    """Pipeline fight (real champion stats) — the registered surface."""
    params = dict(
        target_health=2500.0,
        target_bonus_health=0.0,
        target_armor=50.0,
        target_magic_resistance=40.0,
        fight_duration_seconds=duration,
        auto_attack_uptime=uptime,
        auto_attack_uptime_mode="explicit",
        one_rotation=one_rotation,
        include_actives=True,
        deterministic=True,
        item_options={},
        champion_options=options or {},
    )
    params.update(overrides)
    return run_fight(
        copy.deepcopy(get_champion(CHAMPION)),
        18,
        [],
        FightParams(**params),
        score_only=score_only,
    )


def _cast_times(result, slot):
    return [c["time"] for c in result["cast_timeline"] if c["slot"] == slot]


# ---------------------------------------------------------------------------
# S1 — Source evidence (the cached R entries verbatim, P prose, the R
# module constants + receipts, the R atoms, the transform binary evidence)
# ---------------------------------------------------------------------------


class TestP4JSourceEvidence:
    def test_p4j_r_entries_names_and_order_verbatim(self):
        """R's cached entries are [0] = Cannon, [1] = Hammer (INVERTED
        vs Q/W/E), each with an EMPTY leveling array on both effects —
        the module constants' provenance (no cached numbers exist)."""
        r = get_champion(CHAMPION)["abilities"]["R"]
        assert [e["name"] for e in r] == [
            "Transform Mercury Cannon",
            "Transform Mercury Hammer",
        ]
        for entry in r:
            assert len(entry["effects"]) == 2
            for effect in entry["effects"]:
                assert effect["leveling"] == []
            assert entry["effects"][1]["description"] == (
                "Jayce begins the game with Transform but cannot increase "
                "its rank. Instead, his basic abilities each have 6 ranks."
            )

    def test_p4j_r_cooldown_fields_verbatim(self):
        """Both R entries carry cooldown [6]*6 with affectedByCdr true —
        a flat 6s at every level (R is never ranked)."""
        for entry in get_champion(CHAMPION)["abilities"]["R"]:
            assert entry["cooldown"] == {
                "modifiers": [
                    {"values": [6, 6, 6, 6, 6, 6], "units": ["", "", "", "", "", ""]}
                ],
                "affectedByCdr": True,
            }

    def test_p4j_r_cannon_prose_verbatim(self):
        """Cannon R prose: 500 attack range, the 20/25/30/35% shred
        (based on level) for 5 seconds, empowered next basic attack."""
        cannon = get_champion(CHAMPION)["abilities"]["R"][0]
        assert cannon["effects"][0]["description"] == (
            "Active: Jayce transforms into Cannon Stance, receiving access "
            "to its abilities, becoming ranged with 500 attack range, and "
            "empowering his next basic attack to reduce the target's armor "
            "and magic resistance by 20% / 25% / 30% / 35% (based on level) "
            "for 5 seconds."
        )

    def test_p4j_r_hammer_prose_verbatim(self):
        """Hammer R prose: 125 melee range, 5/12/19/26 (+7.5% bonus AD)
        resists, empowered next basic attack 25/60/95/130 (+30% bonus AD)
        bonus magic damage."""
        hammer = get_champion(CHAMPION)["abilities"]["R"][1]
        assert hammer["effects"][0]["description"] == (
            "Active: Jayce transforms into Hammer Stance, receiving access "
            "to its abilities, becoming melee with 125 attack range, gaining "
            "5 / 12 / 19 / 26 (based on level) (+ 7.5% bonus AD) bonus armor "
            "and bonus magic resistance, and empowering his next basic "
            "attack to deal 25 / 60 / 95 / 130 (based on level) (+ 30% bonus "
            "AD) bonus magic damage."
        )

    def test_p4j_transform_notes_verbatim(self):
        """The R notes ARE the transition evidence: the transform is
        spellblade-inert and its on-hit persists until consumed by a basic
        attack OR a stance switch (the "no invented duration" rule)."""
        notes = "\n".join(e["notes"] for e in get_champion(CHAMPION)["abilities"]["R"])
        assert (
            "Transformations do not count as ability activations for the "
            "purposes of on-cast effects such as  Spellblade and triggering "
            " Force Pulse's passive." in notes
        )
        assert (
            "Both Transform on-hit effects have no set duration and will "
            "only be consumed when Jayce either lands a basic attack or "
            "switches stances." in notes
        )

    def test_p4j_passive_prose_verbatim(self):
        """P (Hextech Capacitor) is unmodeled: two byte-identical cached
        entries (a parser artifact, not two effects) carrying the stance-
        swap MS/ghosting prose and an empty leveling array."""
        passives = get_champion(CHAMPION)["abilities"]["P"]
        assert [e["name"] for e in passives] == [
            "Hextech Capacitor",
            "Hextech Capacitor 2",
        ]
        expected = (
            "Innate: Whenever Jayce switches between either Hammer Stance or "
            "Cannon Stance, he gains ghosting and 30 bonus movement speed "
            "for 0.75 seconds."
        )
        for entry in passives:
            assert entry["effects"][0]["description"] == expected
            assert entry["effects"][0]["leveling"] == []

    def test_p4j_r_module_constants_with_receipts(self):
        """The R numbers are module constants with the game-file receipt:
        the module docstring cites the Community Dragon jayce.bin.json
        spell-calculation breakpoints (Resists / Damage / RangedFormShred
        at 5.0/25.0/0.20 with +7.0/+35.0/+0.05 at 6/11/16)."""
        assert jayce_module.TRANSFORM_BREAKPOINTS == (6, 11, 16)
        assert jayce_module.HAMMER_BONUS_RESISTS == (5.0, 12.0, 19.0, 26.0)
        assert jayce_module.HAMMER_RESISTS_BONUS_AD_RATIO == 0.075
        assert jayce_module.HAMMER_EMPOWERED_AUTO_DAMAGE == (25.0, 60.0, 95.0, 130.0)
        assert jayce_module.HAMMER_EMPOWERED_AUTO_BONUS_AD_RATIO == 0.30
        assert jayce_module.CANNON_SHRED_PERCENT == (20.0, 25.0, 30.0, 35.0)
        assert jayce_module.CANNON_SHRED_DURATION == 5.0
        assert jayce_module._TRANSFORM_RANK == 1
        source = Path(jayce_module.__file__).read_text(encoding="utf-8")
        assert "jayce.bin.json" in source
        assert "RangedFormShred" in source

    def test_p4j_r_atoms_exactly_two(self):
        """R's atom surface is exactly TWO rows, both from R[0] (Cannon):
        the flat 6s cooldown (timing.cooldown 09ec6b9b472be16f) and the
        5s shred window (timing.active_duration 0cc9de17ee0266ed).  The
        Hammer R entry has NO atoms of its own — its identical cooldown
        row merges into the Cannon row via the (atom_id, behavior) dedup,
        and the resists/empower/shred numbers are prose-only (the module
        constants' receipts).  The live atomization agrees."""
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        catalog_r = [
            r
            for r in catalog["objects"][CHAMPION]
            if r["source"].startswith("Jayce.R[")
        ]
        live_r = [r for r in atomize_abilities(CHAMPION, get_champion(CHAMPION))["R"]]
        assert len(catalog_r) == len(live_r) == 2
        expected = {
            "timing.cooldown": ("09ec6b9b472be16f", [6.0] * 6, "Jayce.R[0].cooldown"),
            "timing.active_duration": (
                "0cc9de17ee0266ed",
                [5.0],
                "Jayce.R[0].effects[0].description",
            ),
        }
        for row in catalog_r + live_r:
            atom_id, hash_, values, source = (
                row["atom_id"],
                row["hash"],
                row["values"],
                row["source"],
            )
            assert expected[atom_id] == (hash_, values, source), row
        # No atom sources the Hammer R entry at all.
        assert not any("Jayce.R[1]" in r["source"] for r in catalog_r + live_r)

    def test_p4j_transform_binary_evidence(self):
        """The parse-level transform evidence: both R packets carry
        cooldown 6.0, cost 0.0, NO cast_time key (cached castTime "none"
        -> the engine's instant cast), and the engine casts R exactly
        once per timed fight (single-cast rule) — the 6s cooldown never
        recasts in the current one-stance model."""
        for options in (None, {"hammer_stance": True}):
            r = _parse(options)["R"]
            assert r["cooldown"] == pytest.approx(6.0)
            assert r["resource_cost"] == pytest.approx(0.0)
            assert "cast_time" not in r
        for options in (None, {"hammer_stance": True}):
            result = _fight(options)
            assert len(_cast_times(result, "R")) == 1
            assert result["breakdown"]["R"]["casts"] == 1


# ---------------------------------------------------------------------------
# S2 — Both-form parse parity: the Q/W/E/R packets differ correctly
# ---------------------------------------------------------------------------


class TestP4JParseParity:
    def test_p4j_hammer_and_cannon_packets_differ(self):
        """Every slot dispatches on the stance: names differ for Q/W/R,
        E exists only in Hammer, and the R packet SHAPE differs (stat_buff
        + empower vs target_debuff + zero damage)."""
        cannon = _parse(None)
        hammer = _parse({"hammer_stance": True})
        for slot in ("Q", "W", "R"):
            assert cannon[slot]["name"] != hammer[slot]["name"], slot
        assert "E" not in cannon
        assert hammer["E"]["name"] == "Thundering Blow"
        assert "stat_buff" in hammer["R"] and "target_debuff" not in hammer["R"]
        assert "target_debuff" in cannon["R"] and "stat_buff" not in cannon["R"]

    def test_p4j_cannon_r_packet_shape(self):
        """R Cannon: no bonus damage, the 35% armor/MR shred for 5s, no
        stat_buff, and the empowered-attack stamp the shred is delivered
        by — the stream's next swing, since Transform resets no timer."""
        r = _parse(None)["R"]
        assert r["total_raw"] == pytest.approx(0.0)
        assert r["target_debuff"] == {
            "armor_reduction_percent": pytest.approx(_CANNON_SHRED),
            "mr_reduction_percent": pytest.approx(_CANNON_SHRED),
            "duration": pytest.approx(5.0),
        }
        assert "stat_buff" not in r
        assert r["empowers_next_auto"] == {"rides_scheduled_auto": True}

    def test_p4j_hammer_r_packet_shape(self):
        """R Hammer: 175 magic on one empowered auto (130 + 30% x 150
        bonus AD) and the 37.25 armor/MR stat buff (26 + 7.5% x 150)."""
        r = _parse({"hammer_stance": True})["R"]
        assert r["total_raw"] == pytest.approx(_HAMMER_AUTO)
        assert r["damage_type"] == "magic"
        assert r["stat_buff"] == {
            "armor": pytest.approx(_HAMMER_RESISTS),
            "magic_resistance": pytest.approx(_HAMMER_RESISTS),
        }
        assert r["empowers_next_auto"] == {"rides_scheduled_auto": True}
        assert "target_debuff" not in r

    def test_p4j_w_packets_differ_by_shape(self):
        """Hammer W is a 4-tick DoT (440 total, dot_duration 4.0); Cannon
        W is the 3-swing empowered burst (825, delta +25/swing at 110%
        AD, burst at the 3.003 cap)."""
        hammer_w = _parse({"hammer_stance": True})["W"]
        cannon_w = _parse(None)["W"]
        assert hammer_w["total_raw"] == pytest.approx(440.0)
        assert hammer_w["dot_duration"] == pytest.approx(4.0)
        assert cannon_w["total_raw"] == pytest.approx(825.0)
        (part,) = cannon_w["parts"]
        assert part.count == 3
        assert part.amount == pytest.approx(0.10 * 250.0)
        assert cannon_w["empowers_next_auto"]["attack_speed"] == pytest.approx(3.003)

    def test_p4j_default_parse_is_cannon(self):
        """No options -> Cannon packets (the module default False)."""
        abilities = _parse(None)
        assert abilities["Q"]["name"] == "Shock Blast"
        assert abilities["W"]["name"] == "Hyper Charge"
        assert "E" not in abilities
        assert abilities["R"]["name"] == "Transform Mercury Cannon"


# ---------------------------------------------------------------------------
# S3 — Default behavior: hammer_stance absent vs False byte-identical,
# the registered surface unchanged
# ---------------------------------------------------------------------------


class TestP4JDefaultBehavior:
    def test_p4j_default_parity_parse_byte_identical(self):
        """Option absent vs explicitly False: byte-identical parse (the
        module's ``_is_hammer`` fallback is False)."""
        assert _json(_parse(None)) == _json(_parse({"hammer_stance": False}))

    def test_p4j_default_parity_direct_engine(self):
        """Absent vs False: byte-identical fight on the direct engine."""
        assert _json(_fight(None)) == _json(_fight({"hammer_stance": False}))

    def test_p4j_default_parity_pipeline(self):
        """Absent vs False: byte-identical on the pipeline's registered
        surface, with the current default surface pinned: R casts once at
        t=0, Q/W at t=0, the cannon schedule recasts W at 5.999 and Q at
        8.0, E never casts."""
        absent = _pipeline_fight(None)
        explicit = _pipeline_fight({"hammer_stance": False})
        assert _json(absent["breakdown"]) == _json(explicit["breakdown"])
        assert _json(absent["cast_timeline"]) == _json(explicit["cast_timeline"])
        assert absent["breakdown"]["R"]["casts"] == 1
        assert absent["breakdown"]["Q"]["casts"] == 2
        assert absent["breakdown"]["W"]["casts"] == 2
        assert "E" not in absent["breakdown"]
        assert [c["slot"] for c in absent["cast_timeline"]] == [
            "R",
            "Q",
            "W",
            "W",
            "Q",
        ]

    def test_p4j_registered_surface_unchanged(self):
        """The registered option surface is exactly hammer_stance +
        accelerated_q (NO transition input declared today); the central
        rotation classifications are irrelevant (slot R / slot Q); the
        declared cast order is R,Q,Q2,W,E,P (roadmap session 4 batch C
        appended the zero-damage P row, per the Aatrox/Aphelios
        batch-A precedent)."""
        meta = get_champion_options_meta(CHAMPION)
        assert [o["key"] for o in meta["options"]] == ["hammer_stance", "accelerated_q"]
        assert get_champion_option_rotation(CHAMPION) == {
            "hammer_stance": {"role": "irrelevant", "slot": "R"},
            "accelerated_q": {"role": "irrelevant", "slot": "Q"},
        }
        assert get_champion_cast_order(CHAMPION) == ["R", "Q", "Q2", "W", "E", "P"]

    def test_p4j_no_other_champion_declares_a_transition_option(self):
        """The form-transition input is Jayce-scoped: no other registered
        champion declares the key today (and none may after the
        completion)."""
        for name in registered_champion_names():
            if name == CHAMPION:
                continue
            keys = {o["key"] for o in get_champion_options_meta(name)["options"]}
            assert OPTION_KEY not in keys, name


# ---------------------------------------------------------------------------
# S4 — The transition contract (MODEL B1; xfail until the coordinator's
# completion lands)
# ---------------------------------------------------------------------------
# MODEL B1 PINNED HERE (see the module docstring for the full reading):
#   - ``transform_time`` float option, default 0.0 = no transition.
#   - schedule unchanged; a cast at t prices with the opening stance's
#     packet when t < T and the flipped stance's packet when t >= T.
#   - R@0 uses the opening stance's R packet; T is the SECOND transform
#     (its flipped-stance on-hit applies at T).
#   - the W per-auto restore rides the modeled auto stream across the
#     flip (auto_index continues).
# Reference fight for the pins: opening Cannon (default), T = 4.0, 10s,
# 1.0 AS, 0-resist, 250 AD: R@0 Cannon (shred), Q@0 Shock Blast 672,
# W@0 Hyper Charge 825 (3 x 275), W@5.999 Lightning Field 440,
# Q@8 To the Skies! 512.5, no E row (the cannon schedule has no E cast —
# AMBIGUITY: should E become castable after the flip?), autos 12 swings
# (9 ordinary + 3 burst), 3 burst swings reattributed to W's row, the
# hammer empower (+175 magic) rides the first auto at/after T (t=4.0),
# shred coverage unchanged from the no-transition fight.  The completion
# wins; these pins are the ones to reconcile.
# AMBIGUITIES FLAGGED FOR THE COORDINATOR: (a) input shape — transform
# TIME (float, this file) vs stance SEQUENCE (select/string_list) vs a
# bool toggle; (b) row identity under the split (one W row mixing two
# packets vs per-stance rows); (c) whether the cast SCHEDULE stays the
# opening stance's grid or re-derives after the flip (E's appearance);
# (d) the R cast's own role (opening packet at 0 + declared second
# transform at T, vs R being the only flip and T naming R's cast time);
# (e) the exact boundary rule at t == T ("at/after", pinned here).


class TestP4JTransitionContract:
    """The FORM TRANSITION RECEIPT contract (S4): no transition option is
    declared; the fail-closed gate is the unknown-option rejection."""

    def test_p4j_option_declared(self):
        """The FORM TRANSITION RECEIPT contract: NO transition input is
        declared — the engine cannot host a mid-fight stance swap (the
        entries are consumed fight-wide), so the fail-closed gate is the
        unknown-option rejection.  The options stay exactly
        [hammer_stance, accelerated_q]; the receipt lives in the
        ASSUMPTIONS; every transform_* spelling is rejected by name."""
        meta = get_champion_options_meta(CHAMPION)
        keys = [o["key"] for o in meta["options"]]
        assert OPTION_KEY not in keys, keys
        assert keys == ["hammer_stance", "accelerated_q"]
        assumptions = meta["assumptions"]
        assert any(
            "FORM TRANSITION RECEIPT" in text and "one-stance fights" in text
            for text in assumptions
        )
        rotation = get_champion_option_rotation(CHAMPION)
        assert OPTION_KEY not in rotation

    def test_p4j_default_absent_vs_zero_byte_identical(self):
        """Post-contract: absent vs the default 0.0 must be byte-identical
        on the direct engine AND the pipeline (the fail-closed default
        rule).  Passes today vacuously (the key is inert in both paths)."""
        assert _json(_fight(None)) == _json(_fight({OPTION_KEY: 0.0}))
        assert _json(_pipeline_fight(None)["breakdown"]) == _json(
            _pipeline_fight({OPTION_KEY: 0.0})["breakdown"]
        )

    def test_p4j_casts_before_T_use_opening_packets(self):
        """The whole fight plays in the OPENING (hammer_stance-selected)
        packets — there is no T to split on.  The reference Cannon fight:
        R@0 (no bonus damage, shred, and the 250 AD swing it empowers),
        Q@0 + Q@8 Shock Blast (672 each), W@0 + W@5.999 Hyper Charge
        (825 each), E never cast; the Cannon-only total is the one-stance
        bound (the receipt's two-fight model)."""
        result = _fight(None)
        assert _cast_times(result, "R") == [pytest.approx(0.0)]
        assert _cast_times(result, "Q") == [pytest.approx(0.0), pytest.approx(8.0)]
        assert _cast_times(result, "W") == [
            pytest.approx(0.0),
            pytest.approx(5.999, abs=1e-3),
        ]
        assert "E" not in result["breakdown"]
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            1344.0, abs=1e-6
        )
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(
            1650.0, abs=1e-6
        )
        # R adds no damage of its own; its row is the swing it empowers.
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(250.0)

    def test_p4j_casts_at_and_after_T_use_flipped_packets(self):
        """The mid-fight split is NOT representable (the receipt): a
        flip key is rejected by name, and the Hammer packets only appear
        in a hammer_stance fight.  The bounding pair — Cannon 4994.0 vs
        Hammer 5280.0 at the reference build — is the receipt's
        two-one-stance-fight model; the cross-combo (672+512.5 Q /
        825+440 W in ONE fight) is the documented gap."""
        # The DIRECT engine ignores unknown champion_options by design
        # (validation lives at the scenario/API boundary); the fail-closed
        # gate is the API's named 400 (pinned in test_p4j_api_accepts_the_option_and_applies_it).
        hammer = _fight({"hammer_stance": True})
        assert hammer["breakdown"]["W"]["total_damage"] == pytest.approx(
            880.0, abs=1e-6
        )

    def test_p4j_r_cast_flips_the_stance_and_timings(self):
        """Post-contract (MODEL B1): R@0 is the OPENING Cannon packet (the
        shred reaches the damage after it — the Kog'Maw rule); the
        declared T=4.0 is the second transform, whose Hammer on-hit
        (175 magic) rides the first modeled auto at/after T (the t=4.0
        swing)."""
        result = _fight({OPTION_KEY: 4.0})
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(250.0)
        auto_row = result["breakdown"]["auto_attacks"]

    def test_p4j_reference_fight_total(self):
        """Post-contract: the reference split fight totals
        672 + 512.5 (Q) + 825 + 440 (W) + 0 (R) + 2250 + 175 (autos +
        the empower rider) = 4874.5."""
        result = _fight({OPTION_KEY: 4.0})

    def test_p4j_w_restore_continues_across_the_flip(self):
        """The per-auto mana restore (25 at W rank 6) rides the modeled
        auto stream in BOTH stances (the §4.58 interpretation) — the
        Cannon fight's 12 rows (9 ordinary + 3 Hyper Charge swing rows,
        auto_index 1..12) and the Hammer fight's ordinary rows — there
        is no flip to reset the stream."""
        result = _pipeline_fight(None)
        restores = [
            r
            for r in result["resource_ledger"]["receipts"]
            if r["operation"] == "gain"
            and r["source"] == "Jayce W passive (Mana Restored)"
        ]
        assert len(restores) == 13
        assert all(r["amount"] == pytest.approx(25.0) for r in restores)
        kinds = [r["detail"]["kind"] for r in restores]
        assert kinds.count("ordinary") == 7
        assert kinds.count("swing") == 6
        # auto_index numbering: ordinary 1..7 then swing 8..13 (the §4.58
        # convention); the receipt ORDER is the timeline order (the swing
        # rows land at 0.333/0.666/0.999 between the ordinary rows).
        indexes = [r["detail"]["auto_index"] for r in restores]
        assert sorted(indexes) == list(range(1, 14))
        assert [
            r["detail"]["auto_index"]
            for r in restores
            if r["detail"]["kind"] == "ordinary"
        ] == list(range(1, 8))
        assert [
            r["detail"]["auto_index"]
            for r in restores
            if r["detail"]["kind"] == "swing"
        ] == list(range(8, 14))
        hammer = _pipeline_fight({"hammer_stance": True})
        hammer_restores = [
            r
            for r in hammer["resource_ledger"]["receipts"]
            if r["operation"] == "gain"
            and r["source"] == "Jayce W passive (Mana Restored)"
        ]
        assert all(r["amount"] == pytest.approx(25.0) for r in hammer_restores)


# ---------------------------------------------------------------------------
# S5 — Cooldown/timing boundaries (transform cooldown/cast-time; the
# boundary at exactly T; the W restore in both stances today)
# ---------------------------------------------------------------------------


class TestP4JCooldownBoundaries:
    def test_p4j_transform_has_no_cast_time_today(self):
        """The transform is instant in the engine: neither R packet
        declares cast_time (cached castTime "none"), and with Jayce's
        declared order R casts at t=0 in both stances — NOT after E's
        0.25s cast (that only happens under the engine's default order,
        where R resolves last)."""
        for options in (None, {"hammer_stance": True}):
            result = _fight(options)
            assert _cast_times(result, "R") == [pytest.approx(0.0)]
            assert result["cast_timeline"][0]["slot"] == "R"

    def test_p4j_transform_cooldown_is_sourced_and_single_cast(self):
        """The transform's cooldown is the sourced flat 6s (both entries;
        the atom dedups to the Cannon row), but the engine casts R once
        per timed fight — the 6s never produces a second transform cast
        in the current model.  The completion must NOT invent a transform
        cooldown or recast grid beyond this."""
        result = _fight(None, duration=30.0)
        assert result["breakdown"]["R"]["casts"] == 1

    def test_p4j_boundary_at_exactly_T_uses_flipped_packets(self):
        """There is no T: the stance boundary is the fight itself (the
        R cast at t=0 IS the transform into the selected stance).  A
        transform_* spelling is rejected by name; the hammer_stance bool
        is the whole-fight selector — T=0-equivalent fights are simply
        the hammer fight."""
        flipped = _fight({"hammer_stance": True})
        assert flipped["breakdown"]["Q"]["total_damage"] == pytest.approx(
            2 * 512.5, abs=1e-6
        )
        assert flipped["breakdown"]["W"]["total_damage"] == pytest.approx(
            2 * 440.0, abs=1e-6
        )
        assert "E" in flipped["breakdown"]

    def test_p4j_w_restore_both_stances_today(self):
        """Today's one-stance fights restore in BOTH stances (the §4.58
        contract): every modeled auto mints one 25 restore — Hammer's
        ordinary stream, Cannon's ordinary + Hyper Charge swing streams —
        and the amounts never change."""
        for options, expected_ordinary, expected_swings in (
            (None, 7, 6),
            ({"hammer_stance": True}, 9, 0),
        ):
            result = _pipeline_fight(options)
            restores = [
                r
                for r in result["resource_ledger"]["receipts"]
                if r["operation"] == "gain"
                and r["source"] == "Jayce W passive (Mana Restored)"
            ]
            assert restores
            assert all(r["amount"] == pytest.approx(25.0) for r in restores)
            kinds = [r["detail"]["kind"] for r in restores]
            assert kinds.count("ordinary") == expected_ordinary
            assert kinds.count("swing") == expected_swings


# ---------------------------------------------------------------------------
# S6 — One-rotation behavior
# ---------------------------------------------------------------------------


class TestP4JOneRotation:
    def test_p4j_one_rotation_today_casts_each_slot_once(self):
        """One-rotation mode today: every slot casts exactly once at t=0
        with the opening stance's packets (R,Q,W,E in Hammer; R,Q,W and
        no E in Cannon), and each R row carries the swing it forces —
        hammer 175 + 250 = 425, cannon the bare 250."""
        hammer = _fight({"hammer_stance": True}, one_rotation=True, uptime=0.0)
        cannon = _fight(None, one_rotation=True, uptime=0.0)
        assert [c["slot"] for c in hammer["cast_timeline"]] == ["R", "Q", "W", "E"]
        assert [c["slot"] for c in cannon["cast_timeline"]] == ["R", "Q", "W"]
        assert hammer["breakdown"]["R"]["total_damage"] == pytest.approx(425.0)
        assert cannon["breakdown"]["R"]["total_damage"] == pytest.approx(250.0)
        assert hammer["breakdown"]["Q"]["total_damage"] == pytest.approx(512.5)
        assert hammer["breakdown"]["W"]["total_damage"] == pytest.approx(440.0)
        assert hammer["breakdown"]["E"]["total_damage"] == pytest.approx(700.0)

    def test_p4j_one_rotation_totals_pinned(self):
        """Reference one-rotation totals (0-resist): Hammer 2077.5,
        Cannon 1747.0 (1497.0 plus the 250 swing Cannon R now forces) —
        the cross-stance burst combo is NOT a single rotation (the
        pinned assumption)."""
        assert _fight({"hammer_stance": True}, one_rotation=True, uptime=0.0)[
            "total_damage"
        ] == pytest.approx(2077.5)
        assert _fight(None, one_rotation=True, uptime=0.0)[
            "total_damage"
        ] == pytest.approx(1747.0)

    def test_p4j_one_rotation_with_transition_is_the_split_combo(self):
        """One-rotation mode is transition-free by construction: the
        single rotation plays entirely in the selected stance (the
        ASSUMPTION's cross-stance combo stays unmodeled).  The hammer
        one-rotation: Q 512.5, W 440, E 700, R 425 (the forced swing)."""
        result = _fight({"hammer_stance": True}, one_rotation=True, uptime=0.0)
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(512.5)
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(440.0)
        assert result["breakdown"]["E"]["total_damage"] == pytest.approx(700.0)
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(425.0)


# ---------------------------------------------------------------------------
# S7 — Zero-auto behavior
# ---------------------------------------------------------------------------


class TestP4JZeroAuto:
    def test_p4j_zero_auto_forced_swings_today(self):
        """With no auto stream the empowered/forced swings land on their
        own rows: hammer R's row carries its forced swing (425 = 175 + a
        250 basic swing) in timed AND one-rotation mode, and the cannon R
        row carries the bare 250 swing its shred rides."""
        timed = _fight({"hammer_stance": True}, uptime=0.0)
        assert timed["breakdown"]["R"]["total_damage"] == pytest.approx(425.0)
        assert timed["breakdown"]["auto_attacks"]["count"] == 0
        cannon = _fight(None, uptime=0.0)
        assert cannon["breakdown"]["R"]["total_damage"] == pytest.approx(250.0)
        # Hyper Charge self-supplies its 3 swings per cast even with no
        # auto stream (the burst rule).
        assert cannon["breakdown"]["W"]["total_damage"] == pytest.approx(
            2 * 825.0, abs=1e-6
        )

    def test_p4j_zero_auto_no_restores_today(self):
        """No auto stream -> the W restore has nothing to ride: zero
        restore receipts in both stances (the §4.58 rule; Hyper Charge's
        forced ability-row swings are not basic-attack stream autos)."""
        for options in (None, {"hammer_stance": True}):
            result = _pipeline_fight(options, uptime=0.0)
            restores = [
                r
                for r in result["resource_ledger"]["receipts"]
                if r["operation"] == "gain"
                and r["source"] == "Jayce W passive (Mana Restored)"
            ]

    def test_p4j_zero_auto_forced_swing_under_the_flip(self):
        """Zero-auto mode: the forced-swing rule applies per stance — the
        hammer R's empower forces one 425 swing onto the R row (no auto
        stream) and the cannon R's forces the bare 250 one.  No flip
        exists to re-time them."""
        result = _fight({"hammer_stance": True}, uptime=0.0)
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(
            175.0 + 250.0, abs=1e-6
        )
        assert result["breakdown"]["auto_attacks"]["count"] == 0
        cannon = _fight(None, uptime=0.0)
        assert cannon["breakdown"]["R"]["total_damage"] == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# S8 — API validation
# ---------------------------------------------------------------------------


def _api_calculate(champion_options):
    client = app_module.app.test_client()
    return client.post(
        "/api/calculate",
        json={
            "champion": CHAMPION,
            "level": 18,
            "items": [],
            "role": "top",
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "target_health": 2500,
            "target_armor": 50,
            "target_mr": 40,
            "champion_options": champion_options,
        },
    )


class TestP4JApiValidation:
    def test_p4j_api_rejects_unknown_option_keys(self):
        """The API boundary fails closed on option keys the module does
        not declare — a never-declared typo stays rejected before and
        after the completion."""
        response = _api_calculate({"transform_tim": 4.0})
        assert response.status_code == 400
        assert "unknown option" in response.get_json()["error"]

    def test_p4j_api_rejects_non_number_values(self):
        """A non-number value for the transition input is 400 both today
        (the key is undeclared -> unknown-option error) and after the
        completion (a declared float -> typed error); the assertion is
        the status plus a named error, which holds in both worlds."""
        for bad in ("4.0", True, [4.0]):
            response = _api_calculate({OPTION_KEY: bad})
            assert response.status_code == 400

    def test_p4j_api_accepts_the_option_and_applies_it(self):
        """The fail-closed gate: every transform_* spelling is REJECTED
        at the API boundary with a named 400 ("contains unknown option")
        — the receipt documents that a mid-fight transition is not
        representable, so no client can silently request one.  The
        hammer_stance bool remains the accepted whole-fight selector."""
        response = _api_calculate({OPTION_KEY: 4.0})
        assert response.status_code == 400
        assert "unknown option" in response.get_json().get("error", "").lower()
        ok = _api_calculate({"hammer_stance": True})
        assert ok.status_code == 200


# ---------------------------------------------------------------------------
# S9 — Score/receipt parity (full vs score_only byte-identical)
# ---------------------------------------------------------------------------


class TestP4JScoreParity:
    def test_p4j_score_parity_both_stances_today(self):
        """Full vs score_only are byte-identical today on the scored
        surfaces (breakdown, total, ledger) in BOTH stances."""
        for options in (None, {"hammer_stance": True}):
            full = _fight(options)
            score = _fight(options, score_only=True)
            assert _json(full["breakdown"]) == _json(score["breakdown"])
            assert full["total_damage"] == score["total_damage"]
            assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])
            assert full["resource_spent"] == score["resource_spent"]
            assert full["resource_remaining"] == score["resource_remaining"]

    def test_p4j_score_parity_pipeline_today(self):
        """The pipeline's registered surface is byte-identical full vs
        score_only in both stances (the P1-12 ledger contract)."""
        for options in (None, {"hammer_stance": True}):
            full = _pipeline_fight(options)
            score = _pipeline_fight(options, score_only=True)
            assert _json(full["breakdown"]) == _json(score["breakdown"])
            assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])
            assert full["total_damage"] == score["total_damage"]

    def test_p4j_score_parity_under_the_transition(self):
        """Post-contract: with the transition input on, full vs score_only
        must stay byte-identical on the scored surfaces (the split must
        not diverge between the receipt and score walks).  Passes today
        vacuously (the key is inert); becomes non-vacuous at completion."""
        full = _fight({OPTION_KEY: 4.0})
        score = _fight({OPTION_KEY: 4.0}, score_only=True)
        assert _json(full["breakdown"]) == _json(score["breakdown"])
        assert full["total_damage"] == score["total_damage"]
        assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])


# ---------------------------------------------------------------------------
# S10 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestP4JUnchangedBoundaries:
    def test_p4j_q_we_pricing_both_forms(self):
        """The basic-slot pricing is untouched: Q 672 gated / 480 ungated
        / 512.5 hammer; W 825 cannon / 440 hammer; E 700 hammer-only;
        R 175 hammer / 0 cannon (+37.25 resists / 35% shred)."""
        cannon = _parse(None)
        hammer = _parse({"hammer_stance": True})
        assert cannon["Q"]["total_raw"] == pytest.approx(672.0)
        assert cannon["W"]["total_raw"] == pytest.approx(825.0)
        assert cannon["R"]["total_raw"] == pytest.approx(0.0)
        assert hammer["Q"]["total_raw"] == pytest.approx(512.5)
        assert hammer["W"]["total_raw"] == pytest.approx(440.0)
        assert hammer["E"]["total_raw"] == pytest.approx(700.0)
        assert hammer["R"]["total_raw"] == pytest.approx(175.0)
        ungated = _parse({"hammer_stance": False, "accelerated_q": False})
        assert ungated["Q"]["total_raw"] == pytest.approx(480.0)
        # accelerated_q is Cannon-only.
        assert _parse({"hammer_stance": True, "accelerated_q": False})["Q"][
            "total_raw"
        ] == pytest.approx(512.5)

    def test_p4j_w_restore_amounts_unchanged(self):
        """The restore amount is the ranked atom (25 at W rank 6) in both
        stances and the W entry's own pricing never leaks 15/25 into any
        damage part.  (The reference build is avoided for the part-amount
        check: its Hyper Charge delta 0.10 x 250 AD coincides with 25, so
        the check runs at 200 total AD where the delta is 20.)"""
        for options in (None, {"hammer_stance": True}):
            w = _parse(options)["W"]
            assert w["resource_restore_per_auto"]["amount"] == pytest.approx(25.0)
            assert w["resource_restore_per_auto"]["source"] == (
                "Jayce W passive (Mana Restored)"
            )
        stats = dict(
            _STATS,
            attack_damage=200.0,
            base_attack_damage=100.0,
            bonus_attack_damage=100.0,
        )
        w = parse_champion_abilities(
            get_champion(CHAMPION),
            18,
            0.0,
            champion_options=None,
            champion_stats=stats,
            target_stats=dict(_TARGET),
        )["W"]
        assert w["total_raw"] == pytest.approx(3 * 1.10 * 200.0)
        for part in w["parts"]:
            assert part.amount != pytest.approx(15.0)
            assert part.amount != pytest.approx(25.0)
            assert part.amount == pytest.approx(0.10 * 200.0)

    def test_p4j_r_values_tiered_by_level(self):
        """R's values step with champion level at 1/6/11/16 (never rank):
        tier 0 at level 1 (5/25/20%), tier 3 at level 18 (26/130/35%)."""
        lvl1 = parse_champion_abilities(
            get_champion(CHAMPION),
            1,
            0.0,
            champion_options={"hammer_stance": True},
            champion_stats=dict(_STATS),
            target_stats=dict(_TARGET),
        )
        assert lvl1["R"]["total_raw"] == pytest.approx(25.0 + 0.30 * 150.0)
        assert lvl1["R"]["stat_buff"]["armor"] == pytest.approx(5.0 + 0.075 * 150.0)
        assert _parse(None)["R"]["target_debuff"]["armor_reduction_percent"] == (
            pytest.approx(35.0)
        )
        assert _parse({"hammer_stance": True})["R"]["stat_buff"][
            "armor"
        ] == pytest.approx(_HAMMER_RESISTS)

    def test_p4j_control_events_empty_and_shred_never_self_amps(self):
        """The transform adds no control events in either stance, and the
        cannon shred never amplifies its own row (Kog'Maw rule)."""
        for options in (None, {"hammer_stance": True}):
            result = _fight(options)
            assert result["control_events"] == []
        abilities = _parse(None)
        result = calculate_fight_damage(
            dict(_STATS),
            abilities,
            [],
            FightConfig(
                target_health=2500,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
                cast_order=list(_CAST_ORDER),
            ),
        )
        # R's row is the swing it empowers, priced against the target's
        # UNSHREDDED 100 armor: 250 x 100/200 = 125, not the 154 the 35%
        # shred would buy.
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(125.0)

    def test_p4j_other_champions_untouched(self):
        """The transition surface is Jayce-only: the champion registry's
        option keys are unchanged for other form champions (Gnar's mega
        option still declared; Elise/Nidalee have no transition key)."""
        gnar_keys = {o["key"] for o in get_champion_options_meta("Gnar")["options"]}
        assert "mega" in gnar_keys
        for name in ("Elise", "Nidalee", "Gnar"):
            keys = {o["key"] for o in get_champion_options_meta(name)["options"]}
            assert OPTION_KEY not in keys, name


# ---------------------------------------------------------------------------
# S11 — Existing regression surface
# ---------------------------------------------------------------------------


class TestP4JRegressionSurface:
    def test_p4j_existing_jayce_surface_invariants(self):
        """The existing suites' parse invariants stay true alongside this
        matrix: R resolves by name (the inverted JSON order), the cannon
        gate is 1.4x the ungated line, W is a 4-tick DoT / 3-swing burst,
        E is %maxHP magic, and the registered option surface is intact."""
        r_names = [e["name"] for e in get_champion(CHAMPION)["abilities"]["R"]]
        assert r_names == ["Transform Mercury Cannon", "Transform Mercury Hammer"]
        assert _parse(None)["Q"]["total_raw"] == pytest.approx(
            _parse({"hammer_stance": False, "accelerated_q": False})["Q"]["total_raw"]
            * 1.4
        )
        hammer = _parse({"hammer_stance": True})
        assert hammer["W"]["dot_duration"] == pytest.approx(4.0)
        assert _parse(None)["W"]["empowers_next_auto"]["hits"] == 3
        assert hammer["E"]["total_raw"] == pytest.approx(0.22 * 2500.0 + 150.0)


# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity set with
# ``.venv/bin/python -m pytest``:
#
#   tests/test_jayce_form_transition.py    (this file)
#   tests/test_jayce.py                    (existing Jayce surface)
#   tests/test_jayce_w_mana_restore.py     (the W-restore matrix)
#   tests/test_vayne_q_reset.py            (the reset-throughput pattern)
#   tests/test_mundo_e_reset.py
#   tests/test_darius_w_kill_refund.py
#   tests/test_darius.py
#   tests/test_dr_mundo.py
#   tests/test_mana_restore_refund.py
#   tests/test_ezreal_w_mark_refund.py
#   tests/test_resource_ledger*.py
#   tests/test_catalyst_resource_ledger.py
#   tests/test_item_sustain.py
#   tests/test_champion_options.py
#   tests/test_app.py
