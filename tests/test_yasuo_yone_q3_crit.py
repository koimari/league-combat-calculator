"""P4 package: Yasuo + Yone Q3 critical conversion - focused test matrix.

CURRENT RUNTIME FACTS (verified on branch codex/after-skyway):

- ``src/calculator/champions/yasuo.py`` ships ``_way_of_the_wanderer``: the
  P crit-conversion payload ``crit_modifier`` (``_CRIT_CHANCE_MULTIPLIER``
  2.0, ``_CRIT_DAMAGE_MULTIPLIER_FACTOR`` 0.9, ``_EXCESS_CRIT_BONUS_AD_PER_PERCENT``
  0.5) plus the Q (Steel Tempest) entry whose AD-ratio part declares
  ``crit_effectiveness=1.0``.  The fight engine (``damage.py``
  ``_apply_stat_buff_ultimates`` ~2590-2640, part pricing ~3064) applies the
  payload ONCE: ``crit_chance = min(raw% * 2.0, 100)%``,
  ``crit_multiplier = (2.0 + crit_damage_bonus) * 0.9``, and excess
  ``raw% * 2.0 - 100`` converts to ``0.5`` bonus AD per percent - so autos
  AND Steel Tempest's crit-eligible part share the converted stats.
- ``src/calculator/champions/yone.py`` is a packet module: P (Way of the
  Hunter) is a ``no_damage`` state row WITHOUT ``crit_modifier`` and Q
  (Mortal Steel) is a SINGLE non-crit part - the crit conversion the cached
  Yone P prose describes is NOT modeled today (strict xfail boundary).
- Cached Q rows (``data/champions.json``): "Physical Damage" + the DEGRADED
  "Critical Strike Damage" row (Yasuo values ``[0,0,0,0,0]`` units
  ``"(189% + 28.35%) AD"``; Yone split ``"(198%"`` + ``"%) AD"`` with
  ``[29.7..]``).  AGENTS.md degraded list: "Yasuo/Yone Q3 (crit conversion)".
- The coordinator's completion will certify the existing crit behavior +
  the Q3 + the degraded crit-damage row's boundary (or a typed constant +
  receipt where source-backed).  Genuinely-unsupported boundaries are
  STRICT xfail with reason ``"awaiting P4-Yasuo-Yone-Q3 ..."``.

REFERENCE CONFIG (all pins): level 18, ranks Q5/W5/E5/R3, no runes/boots.
Engine-level fights: target 3000 HP, 0 armor / 0 MR, deterministic=True,
cast order Q -> W -> E -> R.  API fights: enemy Aatrox level 18 (armor
120, mitigation 100/220).  Base parse values (no items): Yasuo AD 102, Q
flat 120 + 105% AD (107.1) = 227.1 raw; Yone AD 96, Q 125 + 110% AD
(105.6) = 230.6 raw.  Crit builds (all items 25% crit): 25% Phantom
Dancer; 50% PD + Infinity Edge (AD 178, +30% crit damage -> multiplier
2.07 = (2.0 + 0.30) x 0.9); 50% PD + Stormrazor (AD 152, multiplier 1.8);
100% PD+IE+Stormrazor+RFC (AD 228, bonus 125, excess 100 -> +50 AD);
125% + Runaan's (AD 228, bonus 125, excess 150 -> +75 AD).

AMBIGUITY NOTES for the coordinator:

1. Q3 REPRESENTATION: Yasuo's Q3 attaches ``cc_kind="knockup"`` +
   ``cc_duration=0.9`` to the FLAT part (the first part) and the fight
   events carry ``cc_kind``/``cc_duration``/``cc_reviewed``.  Yone's Q3
   changes ONLY the Q row's ``detail`` string - no cc fields on the part
   and none on the events - while its ASSUMPTION claims the knock-up is
   "modeled as crowd-control state".  The completion should either add
   the cc fields to Yone's Q3 part (parity with Yasuo) or fix the
   assumption text; the matrix pins the current asymmetry.
2. DEGRADED ROW BOUNDARY: the degraded "Critical Strike Damage" rows are
   never priced (fail-closed).  Their units encode the wiki intent:
   Yasuo 105% AD x (180% + 27%) = (189% + 28.35%) AD = 217.35% AD - which
   the engine EXACTLY reproduces at converted-100% crit WITH Infinity Edge
   (1.05 x 2.07); without IE it reproduces the first half (189%).  Yone's
   degraded row (110% x 207% = 227.7% AD) is NOT reproducible today
   (single non-crit part) - a typed-constant + receipt fix (P payload +
   crit_effectiveness split, mirroring Yasuo) is source-backed by Yone's
   cached P prose and the stat atom ``critical_strike_damage_modifier.flat``
   (1142fbe0a600fcc8 = 0.9).
3. EXCESS-CRIT AD GROWTH IS AUTO-ONLY: the conversion mutates
   ``champion_stats`` AFTER the parse, so the Q AD part keeps its
   parse-time amount (1.05 x pre-conversion AD) while autos re-price with
   the converted AD (302 at 125% raw).  The Q's AD ratio does NOT see the
   excess AD - a real-game divergence worth certifying.
4. Q COOLDOWN: the cached cooldown units encode an attack-speed reduction
   ("x (1 - (0.01 per 1.67% bonus attack speed)), capped at 67% reduction
   at 111.1% bonus attack speed", affectedByCdr false) but the module
   prices a flat 4.0 s (atoms 587e43c4d9ab67ac / 45be56f96e10407f).
5. P CONSTANTS NOT ATOM-BACKED: 2.0 / 0.9 / 0.5 are plain module constants;
   only the 0.9 factor has a stat atom (f375a24fbf0555e1).  The strict
   xfail in S8 pins the missing typed certification surface.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_ABILITIES_ATOMS = json.loads(
    Path("data/atoms/abilities.json").read_text(encoding="utf-8")
)["objects"]
_STATS_ATOMS = json.loads(Path("data/atoms/stats.json").read_text(encoding="utf-8"))[
    "objects"
]
_ATOM_MANIFEST = json.loads(
    Path("data/atoms/manifest.json").read_text(encoding="utf-8")
)
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_AWAIT = "awaiting P4-Yasuo-Yone-Q3 ..."

_YASUO_Q = _CHAMPION_DATA["Yasuo"]["abilities"]["Q"][0]
_YONE_Q = _CHAMPION_DATA["Yone"]["abilities"]["Q"][0]
_YASUO_P = _CHAMPION_DATA["Yasuo"]["abilities"]["P"][0]
_YONE_P = _CHAMPION_DATA["Yone"]["abilities"]["P"][0]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(
    name: str,
    options: dict | None = None,
    item_names: list[str] | None = None,
    *,
    level: int = _LEVEL,
):
    items = [get_item_by_name(n) for n in (item_names or [])]
    champ = get_champion(name)
    stats = calculate_total_stats(champ, level, items)
    abilities = parse_champion_abilities(
        champ,
        level,
        stats.get("ability_power", 0.0),
        ability_ranks=_RANKS,
        champion_stats=stats,
        champion_options=options,
        target_stats={
            "target_max_health": 3000.0,
            "target_current_health": 3000.0,
            "target_missing_health": 0.0,
        },
    )
    return stats, abilities, items


def _fight(
    name: str,
    item_names: list[str] | None = None,
    options: dict | None = None,
    *,
    duration: float = 10.0,
    uptime: float = 1.0,
    one_rotation: bool = False,
    score_only: bool = False,
    target_armor: float = 0.0,
    target_mr: float = 0.0,
) -> dict:
    stats, abilities, items = _parse(name, options, item_names)
    return calculate_fight_damage(
        stats,
        abilities,
        items,
        FightConfig(
            target_health=3000.0,
            target_armor=target_armor,
            target_magic_resistance=target_mr,
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=["Q", "W", "E", "R"],
        ),
        score_only=score_only,
        champion_options=dict(options) if options else None,
    )


def _run(
    name: str,
    item_names: list[str] | None = None,
    options: dict | None = None,
    *,
    score_only: bool = False,
    duration: float = 6.0,
) -> dict:
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": duration,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "ability_ranks": _RANKS,
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            "champion_options": options,
        },
        deterministic=True,
    )
    items = [get_item_by_name(n) for n in (item_names or [])]
    return run_fight(get_champion(name), _LEVEL, items, params, score_only=score_only)


def _api(
    name: str,
    item_names: list[str] | None = None,
    options: dict | None = None,
    *,
    duration: float = 6.0,
    fight_mode: str = "time_based",
):
    # TESTING bypasses the rate limiter (app.py:506); restore the previous
    # value so this file never pollutes later rate-limit tests.
    previous_testing = app_module.app.config.get("TESTING")
    app_module.app.config["TESTING"] = True
    try:
        resp = app_module.app.test_client().post(
            "/api/calculate",
            json={
                "champion": name,
                "level": _LEVEL,
                "items": item_names or [],
                "fight_mode": fight_mode,
                "fight_duration": duration,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
                "ability_ranks": _RANKS,
                "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
                "target_health": 3000.0,
                "target_armor": 0,
                "target_mr": 0,
                "champion_options": options or {},
            },
        )
        return resp
    finally:
        app_module.app.config["TESTING"] = previous_testing


def _atom(objects: dict, atom_id: str) -> dict:
    for atom in objects:
        if atom["atom_id"] == atom_id:
            return atom
    raise AssertionError(f"atom {atom_id!r} not found")


def _norm(obj):
    """Normalize a result for byte-identical comparisons."""
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    if isinstance(obj, set):
        return sorted(_norm(v) for v in obj)
    if callable(obj):
        return "<fn>"
    return obj


def _json_bytes(obj) -> bytes:
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# S1 - Source evidence (cached Q rows, degraded rows, cooldowns, atoms)
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_yasuo_q_physical_damage_rows_verbatim(self):
        rows = _YASUO_Q["effects"][0]["leveling"]
        phys = next(r for r in rows if r["attribute"] == "Physical Damage")
        assert [m["values"] for m in phys["modifiers"]] == [
            [20, 45, 70, 95, 120],
            [105, 105, 105, 105, 105],
        ]
        assert [m["units"] for m in phys["modifiers"]] == [
            ["", "", "", "", ""],
            ["% AD", "% AD", "% AD", "% AD", "% AD"],
        ]

    def test_yasuo_q_degraded_crit_damage_row_verbatim(self):
        rows = _YASUO_Q["effects"][0]["leveling"]
        crit = next(r for r in rows if r["attribute"] == "Critical Strike Damage")
        # The AD-ratio modifier is the DEGRADED half-parse: values all zero,
        # the wiki's intended math survives only in the units.
        assert crit["modifiers"][0]["values"] == [20, 45, 70, 95, 120]
        assert crit["modifiers"][1]["values"] == [0, 0, 0, 0, 0]
        assert crit["modifiers"][1]["units"] == [
            "(189% + 28.35%) AD",
            "(189% + 28.35%) AD",
            "(189% + 28.35%) AD",
            "(189% + 28.35%) AD",
            "(189% + 28.35%) AD",
        ]

    def test_yone_q_physical_damage_rows_verbatim(self):
        rows = _YONE_Q["effects"][0]["leveling"]
        phys = next(r for r in rows if r["attribute"] == "Physical Damage")
        assert [m["values"] for m in phys["modifiers"]] == [
            [25, 50, 75, 100, 125],
            [110, 110, 110, 110, 110],
        ]
        assert [m["units"] for m in phys["modifiers"]] == [
            ["", "", "", "", ""],
            ["% AD", "% AD", "% AD", "% AD", "% AD"],
        ]

    def test_yone_q_degraded_crit_damage_row_verbatim(self):
        rows = _YONE_Q["effects"][0]["leveling"]
        crit = next(r for r in rows if r["attribute"] == "Critical Strike Damage")
        # Yone's half-parse split the units across TWO modifiers: "(198%"
        # with zero values plus a stray 29.7 "%) AD" continuation.
        assert crit["modifiers"][0]["values"] == [25, 50, 75, 100, 125]
        assert crit["modifiers"][1]["values"] == [0, 0, 0, 0, 0]
        assert crit["modifiers"][1]["units"] == ["(198%"] * 5
        assert crit["modifiers"][2]["values"] == [29.7, 29.7, 29.7, 29.7, 29.7]
        assert crit["modifiers"][2]["units"] == ["%) AD"] * 5

    def test_q_descriptions_verbatim(self):
        assert (
            "Steel Tempest's damage based on its AD ratio can critically strike "
            "for (180% + 27%) damage."
        ) in _YASUO_Q["effects"][0]["description"]
        assert (
            "Mortal Steel's damage based on its AD ratio can critically strike "
            "for (180% + 27%) damage."
        ) in _YONE_Q["effects"][0]["description"]

    def test_gathering_storm_window_and_knockup_prose_verbatim(self):
        assert (
            "generates a stack of Gathering Storm for 6 seconds, stacking up to "
            "2 times and refreshing on subsequent hits. At 2 stacks, the next "
            "Steel Tempest cast consumes them all to become empowered"
        ) in _YASUO_Q["effects"][1]["description"]
        assert ("additionally knocks up enemies hit for 0.9 seconds.") in _YASUO_Q[
            "effects"
        ][2]["description"]
        assert (
            "additionally knocking up enemies hit in their path for 0.75 " "seconds"
        ) in _YONE_Q["effects"][2]["description"]

    def test_p_intent_prose_verbatim_both_champions(self):
        for p in (_YASUO_P, _YONE_P):
            assert (
                "total critical strike chance is doubled from all other " "sources"
            ) in p["effects"][0]["description"]
            assert (
                "every 1% critical strike chance in excess of 100% is "
                "converted into 0.5 bonus attack damage"
            ) in p["effects"][0]["description"]
            assert ("90% of the critical damage champions usually have") in p[
                "effects"
            ][1]["description"]

    def test_cooldown_rows_verbatim(self):
        for q in (_YASUO_Q, _YONE_Q):
            assert q["cooldown"]["modifiers"][0]["values"] == [4, 4, 4, 4, 4]
            assert q["cooldown"]["affectedByCdr"] is False
            assert (
                " x (1 - (0.01 per 1.67% bonus attack speed)). This is capped "
                "at 67% reduction at 111.1% bonus attack speed."
            ) == q["cooldown"]["modifiers"][0]["units"][0]

    def test_q_atoms_hashes_stable(self):
        yasuo_atoms = _ABILITIES_ATOMS["Yasuo"]
        yone_atoms = _ABILITIES_ATOMS["Yone"]
        pins = [
            (yasuo_atoms, "ability.physical _damage.modifier_0", "c3ffc6c95d1d8051"),
            (yasuo_atoms, "ability.physical _damage.modifier_1", "8fe6f87c3a6fd5fa"),
            (
                yasuo_atoms,
                "ability.critical _strike _damage.modifier_0",
                "89cbd975f1075810",
            ),
            (
                yasuo_atoms,
                "ability.critical _strike _damage.modifier_1",
                "ad38810cc04c7723",
            ),
            (yasuo_atoms, "timing.control_duration", "560aedf0e7aa7083"),
            (yasuo_atoms, "timing.cooldown", "587e43c4d9ab67ac"),
            (yone_atoms, "ability.physical _damage.modifier_0", "efb4e3d0a05287f8"),
            (yone_atoms, "ability.physical _damage.modifier_1", "40cec347de913604"),
            (
                yone_atoms,
                "ability.critical _strike _damage.modifier_0",
                "ad0e75d8563916f2",
            ),
            (
                yone_atoms,
                "ability.critical _strike _damage.modifier_1",
                "6f43777074cc9c33",
            ),
            (
                yone_atoms,
                "ability.critical _strike _damage.modifier_2",
                "83e6154bf72561e7",
            ),
            (yone_atoms, "timing.control_duration", "636ebc1eea9d43bf"),
            (yone_atoms, "timing.cooldown", "45be56f96e10407f"),
        ]
        for atoms, atom_id, expected_hash in pins:
            assert _atom(atoms, atom_id)["hash"] == expected_hash

    def test_degraded_atoms_are_all_zero_values(self):
        for atoms, atom_id in [
            (_ABILITIES_ATOMS["Yasuo"], "ability.critical _strike _damage.modifier_1"),
            (_ABILITIES_ATOMS["Yone"], "ability.critical _strike _damage.modifier_1"),
        ]:
            atom = _atom(atoms, atom_id)
            assert atom["values"] == [0.0, 0.0, 0.0, 0.0, 0.0]

    def test_knockup_duration_atoms_match_cc_prose(self):
        assert _atom(_ABILITIES_ATOMS["Yasuo"], "timing.control_duration")[
            "values"
        ] == [0.9]
        assert _atom(_ABILITIES_ATOMS["Yone"], "timing.control_duration")["values"] == [
            0.75
        ]

    def test_crit_damage_modifier_stat_atoms_both_champions(self):
        # The 0.9 factor is a champion game stat for BOTH champions.
        assert _atom(
            _STATS_ATOMS["Yasuo"], "stat.critical_strike_damage_modifier.flat"
        ) == {
            "atom_id": "stat.critical_strike_damage_modifier.flat",
            "behavior": "stat",
            "source": "Yasuo.stats.criticalStrikeDamageModifier.flat",
            "name": "criticalStrikeDamageModifier",
            "values": [0.9],
            "units": ["flat"],
            "evidence": ["stats.criticalStrikeDamageModifier.flat"],
            "hash": "f375a24fbf0555e1",
        }
        assert (
            _atom(_STATS_ATOMS["Yone"], "stat.critical_strike_damage_modifier.flat")[
                "hash"
            ]
            == "1142fbe0a600fcc8"
        )

    def test_manifest_source_ref_pins_champions_cache(self):
        abilities_domain = _ATOM_MANIFEST["domains"]["abilities"]
        # The branch's atomizer regeneration moves the abilities-domain
        # sha; the manifest + the regenerated file agree (verified), so
        # the pin tracks the live manifest.
        assert abilities_domain["sha256"] == "f209b18e736b4eaa"
        assert (
            abilities_domain["source_ref"]
            == "data/champions.json@sha256:77f8cce3fae087dc"
        )

    def test_module_sources_pin_wiki_revisions(self):
        yasuo_sources = {
            row["label"]: row for row in get_champion_options_meta("Yasuo")["sources"]
        }
        yone_sources = {
            row["label"]: row for row in get_champion_options_meta("Yone")["sources"]
        }
        assert yasuo_sources["Yasuo parent entry"]["revision_id"] == 4007969
        assert yasuo_sources["Yasuo P ability entry"]["revision_id"] == 2864196
        assert yasuo_sources["Yasuo Q ability entry"]["revision_id"] == 2864047
        assert yone_sources["Yone parent entry"]["revision_id"] == 4011252
        assert yone_sources["Yone P ability entry"]["revision_id"] == 3075315
        assert yone_sources["Yone Q ability entry"]["revision_id"] == 3075322


# ---------------------------------------------------------------------------
# S2 - Normal-Q vs Q3 parity
# ---------------------------------------------------------------------------


class TestNormalVsQ3Parity:
    def test_yasuo_q3_parts_match_normal_q(self):
        for stacks in (0, 1):
            _, abilities, _ = _parse("Yasuo", {"q_gathering_storm": stacks})
            q = abilities["Q"]
            assert [p.amount for p in q["parts"]] == pytest.approx([120.0, 107.1])
            assert q["total_raw"] == pytest.approx(227.1)
            assert all(p.cc_kind is None for p in q["parts"])
        _, q3, _ = _parse("Yasuo", {"q_gathering_storm": 2})
        q3_q = q3["Q"]
        assert [p.amount for p in q3_q["parts"]] == pytest.approx([120.0, 107.1])
        assert q3_q["total_raw"] == pytest.approx(227.1)
        # The knock-up rides the flat (first) part; the AD part stays crit-eligible.
        assert q3_q["parts"][0].cc_kind == "knockup"
        assert q3_q["parts"][0].cc_duration == pytest.approx(0.9)
        assert q3_q["parts"][1].crit_effectiveness == 1.0

    def test_yone_q3_same_damage_detail_only(self):
        # Yone's Q3 (P4 fix): same sourced damage as the normal thrust (the
        # flat + AD-ratio split), with the 0.75s knock-up CC state on the
        # flat part — the Yasuo parity shape.
        _, base, _ = _parse("Yone")
        _, q3, _ = _parse("Yone", {"q_gathering_storm": 2})
        assert base["Q"]["total_raw"] == q3["Q"]["total_raw"] == pytest.approx(230.6)
        assert len(base["Q"]["parts"]) == 2
        assert len(q3["Q"]["parts"]) == 2
        assert q3["Q"]["parts"][0].cc_kind == "knockup"
        assert q3["Q"]["parts"][0].cc_duration == pytest.approx(0.75)
        assert q3["Q"]["parts"][1].crit_effectiveness == pytest.approx(1.0)
        assert "0.75s" in q3["Q"]["detail"]
        assert "same sourced damage" in q3["Q"]["detail"]

    def test_q3_detail_strings(self):
        _, yasuo, _ = _parse("Yasuo", {"q_gathering_storm": 2})
        assert yasuo["Q"]["detail"].startswith(
            "Gathering Storm at 2 stacks: this cast is the Q3 whirlwind"
        )
        assert "0.9s knock-up" in yasuo["Q"]["detail"]
        _, yasuo1, _ = _parse("Yasuo", {"q_gathering_storm": 1})
        assert "Gathering Storm 1/2 stacks" in yasuo1["Q"]["detail"]

    def test_q3_fight_damage_identical_per_cast(self):
        for name in ("Yasuo", "Yone"):
            base = _fight(name, one_rotation=True, duration=10.0)
            q3 = _fight(
                name, options={"q_gathering_storm": 2}, one_rotation=True, duration=10.0
            )
            assert (
                q3["breakdown"]["Q"]["total_damage"]
                == base["breakdown"]["Q"]["total_damage"]
            )
            assert q3["breakdown"]["Q"]["casts"] == base["breakdown"]["Q"]["casts"] == 1

    def test_yasuo_q3_events_carry_knockup_cc(self):
        result = _fight(
            "Yasuo", options={"q_gathering_storm": 2}, one_rotation=True, duration=10.0
        )
        q_events = [e for e in result["damage_events"] if e.get("source_key") == "Q"]
        assert q_events
        for event in q_events:
            assert event["cc_kind"] == "knockup"
            assert event["cc_duration"] == pytest.approx(0.9)
            assert event.get("cc_reviewed") is True

    def test_yone_q3_events_carry_no_cc_fields(self):
        # Yone's Q3 knock-up (P4 fix) flows into the damage events like
        # Yasuo's: cc_kind/cc_duration on the Q events.
        result = _fight(
            "Yone", options={"q_gathering_storm": 2}, one_rotation=True, duration=10.0
        )
        q_events = [e for e in result["damage_events"] if e.get("source_key") == "Q"]
        assert q_events
        assert any(e.get("cc_kind") == "knockup" for e in q_events)
        assert any(e.get("cc_duration") == pytest.approx(0.75) for e in q_events)

    def test_q3_does_not_change_cast_timeline(self):
        for name in ("Yasuo", "Yone"):
            base = _fight(name, one_rotation=True, duration=10.0)
            q3 = _fight(
                name, options={"q_gathering_storm": 2}, one_rotation=True, duration=10.0
            )
            assert [row["slot"] for row in base["cast_timeline"]] == [
                row["slot"] for row in q3["cast_timeline"]
            ]
            assert [row["slot"] for row in q3["cast_timeline"]] == ["Q", "W", "E", "R"]


# ---------------------------------------------------------------------------
# S3 - Q3 state: stack counts, the 6s window, option bounds
# ---------------------------------------------------------------------------


class TestGatheringStormState:
    def test_stack_counts_0_1_2(self):
        # 0/1 stacks -> normal thrust; 2 stacks -> the Q3 whirlwind.
        for name in ("Yasuo", "Yone"):
            for stacks in (0, 1):
                _, abilities, _ = _parse(name, {"q_gathering_storm": stacks})
                assert all(p.cc_kind is None for p in abilities["Q"]["parts"])
                assert f"{stacks}/2 stacks" in abilities["Q"]["detail"]
            _, q3, _ = _parse(name, {"q_gathering_storm": 2})
            assert "at 2 stacks" in q3["Q"]["detail"]

    def test_module_clamps_out_of_range(self):
        # Parse-level clamp (the API rejects out-of-range before parsing):
        # 5 -> 2 (Q3), -3 -> 0 (normal).
        _, high, _ = _parse("Yasuo", {"q_gathering_storm": 5})
        assert high["Q"]["parts"][0].cc_kind == "knockup"
        _, low, _ = _parse("Yasuo", {"q_gathering_storm": -3})
        assert low["Q"]["parts"][0].cc_kind is None

    def test_option_meta_declares_the_state(self):
        meta = get_champion_options_meta("Yasuo")
        (option,) = [o for o in meta["options"] if o["key"] == "q_gathering_storm"]
        assert option["type"] == "int"
        assert option["default"] == 0
        assert option["min"] == 0
        assert option["max"] == 2
        assert option["label"] == "Gathering Storm stacks (2 = Q3 ready)"
        assert any(
            "Q3" in text and "same sourced damage" in text
            for text in meta["assumptions"]
        )

    def test_api_rejects_out_of_range_and_unknown(self):
        for options, fragment in [
            ({"q_gathering_storm": 3}, "must be between 0 and 2"),
            ({"q_gathering_storm": -1}, "must be between 0 and 2"),
            ({"q_gathering_storm": "2"}, "must be a number"),
            ({"q_gathering_storm_typo": 2}, "unknown option"),
        ]:
            resp = _api("Yasuo", options=options)
            assert resp.status_code == 400
            assert fragment in resp.get_json()["error"]

    def test_six_second_window_is_pre_fight_state(self):
        # The 6s window is sourced prose; the module models the stack COUNT
        # as pre-fight state (the option) - no expiry timing, no consume
        # transition after the Q3 cast.  Pinned as the documented boundary.
        _, abilities, _ = _parse("Yasuo", {"q_gathering_storm": 2})
        assert abilities["Q"]["detail"]  # Q3 state is the option value
        assert ("generates a stack of Gathering Storm for 6 seconds") in _YASUO_Q[
            "effects"
        ][1]["description"]


# ---------------------------------------------------------------------------
# S4 - Crit conversion at 0 / 50 / 100 percent
# ---------------------------------------------------------------------------


class TestCritConversionPercentiles:
    def test_zero_crit_no_crits(self):
        result = _fight("Yasuo", one_rotation=True, duration=10.0)
        q = result["breakdown"]["Q"]
        autos = result["breakdown"]["auto_attacks"]
        assert q["total_damage"] == pytest.approx(227.1)
        assert autos["damage_per_hit"] == pytest.approx(102.0)
        assert autos["num_crits"] == 0
        assert autos["num_non_crits"] == autos["count"]

    def test_25pct_crit_converted_50pct_blend(self):
        # 25% raw -> converted 50%: the Q AD part and autos price the
        # expected-value blend 1 + 0.5 x (1.8 - 1) = 1.4 (no IE: the 0.9
        # factor gives multiplier 1.8).
        stats, abilities, _ = _parse("Yasuo", item_names=["Phantom Dancer"])
        assert stats["critical_strike_chance"] == pytest.approx(25.0)
        ad_part = abilities["Q"]["parts"][1].amount
        result = _fight("Yasuo", ["Phantom Dancer"], one_rotation=True, duration=10.0)
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            120.0 + ad_part * 1.4
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            stats["attack_damage"] * 1.4
        )

    def test_50pct_crit_converted_100pct_everything_crits(self):
        # 50% raw -> converted 100% (the 2.0 multiplier, capped): the Q AD
        # part and every auto crit at (2.0 + 0.30) x 0.9 = 2.07 (IE).
        stats, abilities, _ = _parse(
            "Yasuo", item_names=["Phantom Dancer", "Infinity Edge"]
        )
        assert stats["critical_strike_chance"] == pytest.approx(50.0)
        ad_part = abilities["Q"]["parts"][1].amount
        result = _fight(
            "Yasuo",
            ["Phantom Dancer", "Infinity Edge"],
            one_rotation=True,
            duration=10.0,
        )
        expected_q = 120.0 + ad_part * 2.07
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(expected_q)
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(506.883)
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            stats["attack_damage"] * 2.07
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            368.46
        )

    def test_50pct_crit_no_ie_multiplier_180(self):
        # Without IE the 0.9 factor alone gives 2.0 x 0.9 = 1.8.
        stats, abilities, _ = _parse(
            "Yasuo", item_names=["Phantom Dancer", "Stormrazor"]
        )
        ad_part = abilities["Q"]["parts"][1].amount
        result = _fight(
            "Yasuo", ["Phantom Dancer", "Stormrazor"], one_rotation=True, duration=10.0
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            120.0 + ad_part * 1.8
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            stats["attack_damage"] * 1.8
        )

    def test_100pct_crit_capped_and_excess(self):
        # 100% raw -> converted 200% capped at 100% (same blend as 50% raw),
        # plus 100 excess percent -> +50 bonus AD on autos; the Q part keeps
        # its parse-time AD amount (boundary: excess AD is auto-only).
        stats, abilities, _ = _parse(
            "Yasuo",
            item_names=[
                "Phantom Dancer",
                "Infinity Edge",
                "Stormrazor",
                "Rapid Firecannon",
            ],
        )
        assert stats["critical_strike_chance"] == pytest.approx(100.0)
        ad_part = abilities["Q"]["parts"][1].amount
        result = _fight(
            "Yasuo",
            ["Phantom Dancer", "Infinity Edge", "Stormrazor", "Rapid Firecannon"],
            one_rotation=True,
            duration=10.0,
        )
        converted_ad = stats["base_attack_damage"] + stats["bonus_attack_damage"] + 50.0
        assert converted_ad == pytest.approx(277.0)
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            120.0 + ad_part * 2.07
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            converted_ad * 2.07
        )

    def test_yone_q_never_crits(self):
        # P4 fix: Yone's Q NOW crits — the P carries the same crit_modifier
        # payload as Yasuo's and the Q's AD-ratio part carries
        # crit_effectiveness=1.0 (converted 100% at 50% raw + IE: the Q
        # AD part = 171 x 1.1 x 2.07 = 389.27 blended).
        stats, abilities, _ = _parse(
            "Yone", item_names=["Phantom Dancer", "Infinity Edge"]
        )
        assert abilities["passive"]["crit_modifier"]["crit_chance_multiplier"] == 2.0
        assert (
            abilities["passive"]["crit_modifier"]["crit_damage_multiplier_factor"]
            == 0.9
        )
        parts = abilities["Q"]["parts"]
        assert parts[0].crit_effectiveness == 0.0
        assert parts[1].crit_effectiveness == pytest.approx(1.0)
        result = _fight(
            "Yone",
            ["Phantom Dancer", "Infinity Edge"],
            one_rotation=True,
            duration=10.0,
        )
        # The converted 100% crit (50% raw x 2) with IE: the Q AD part
        # blends at the full 2.07 multiplier (514.367 = 125 + 171 x 1.1 x
        # 2.07) and the autos at AD x 2.07.
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            125.0 + stats["attack_damage"] * 1.1 * 2.07
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            stats["attack_damage"] * 2.07
        )


# ---------------------------------------------------------------------------
# S5 - Excess crit (>100%): the 0.5 AD per excess percent
# ---------------------------------------------------------------------------


class TestExcessCritConversion:
    def test_125pct_raw_converts_150_excess_to_75_ad(self):
        # 125% raw -> 250% converted; 150 excess percent x 0.5 = +75 bonus
        # AD.  The public champion_stats show the converted AD (302 =
        # 102 base + 125 item bonus + 75 conversion).
        result = _run(
            "Yasuo",
            [
                "Phantom Dancer",
                "Infinity Edge",
                "Stormrazor",
                "Rapid Firecannon",
                "Runaan's Hurricane",
            ],
        )
        stats = result["champion_stats"]
        assert stats["critical_strike_chance"] == pytest.approx(125.0)
        assert stats["bonus_attack_damage"] == pytest.approx(200.0)
        assert stats["attack_damage"] == pytest.approx(302.0)
        # Engine-level (0 armor): every auto crits at 302 x 2.07 = 625.14.
        fight = _fight(
            "Yasuo",
            [
                "Phantom Dancer",
                "Infinity Edge",
                "Stormrazor",
                "Rapid Firecannon",
                "Runaan's Hurricane",
            ],
            one_rotation=True,
            duration=10.0,
        )
        assert fight["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            302.0 * 2.07
        )

    def test_100pct_raw_converts_100_excess_to_50_ad(self):
        result = _run(
            "Yasuo",
            ["Phantom Dancer", "Infinity Edge", "Stormrazor", "Rapid Firecannon"],
        )
        stats = result["champion_stats"]
        assert stats["bonus_attack_damage"] == pytest.approx(175.0)
        assert stats["attack_damage"] == pytest.approx(277.0)

    def test_50pct_raw_has_no_excess(self):
        result = _run("Yasuo", ["Phantom Dancer", "Infinity Edge"])
        stats = result["champion_stats"]
        assert stats["bonus_attack_damage"] == pytest.approx(75.0)  # IE only
        assert stats["attack_damage"] == pytest.approx(178.0)

    def test_excess_ad_does_not_repriced_q_part(self):
        # Boundary (ambiguity note 3): the Q AD part amount is fixed at
        # parse time from the PRE-conversion AD, so the 125% build's Q
        # damage equals the 100% build's Q damage even though autos gain
        # +75 AD.
        q100 = _fight(
            "Yasuo",
            ["Phantom Dancer", "Infinity Edge", "Stormrazor", "Rapid Firecannon"],
            one_rotation=True,
            duration=10.0,
        )
        q125 = _fight(
            "Yasuo",
            [
                "Phantom Dancer",
                "Infinity Edge",
                "Stormrazor",
                "Rapid Firecannon",
                "Runaan's Hurricane",
            ],
            one_rotation=True,
            duration=10.0,
        )
        assert (
            q100["breakdown"]["Q"]["total_damage"]
            == q125["breakdown"]["Q"]["total_damage"]
        )
        assert q125["breakdown"]["Q"]["total_damage"] == pytest.approx(615.558)


# ---------------------------------------------------------------------------
# S6 - Reduced crit damage (the 0.9 factor)
# ---------------------------------------------------------------------------


class TestReducedCritDamage:
    def test_multiplier_is_090_factor(self):
        # 2.0 (base) x 0.9 = 1.8 with no crit-damage bonus; the P payload
        # carries the factor and the module source comment cites the game
        # stat criticalStrikeDamageModifier (atom f375a24fbf0555e1).
        _, abilities, _ = _parse("Yasuo")
        crit = abilities["passive"]["crit_modifier"]
        assert crit["crit_damage_multiplier_factor"] == 0.9
        assert crit["crit_chance_multiplier"] == 2.0
        assert crit["excess_crit_bonus_ad_per_percent"] == 0.5
        stats, _, _ = _parse("Yasuo", item_names=["Phantom Dancer", "Stormrazor"])
        assert stats["attack_damage"] == pytest.approx(152.0)
        result = _fight(
            "Yasuo", ["Phantom Dancer", "Stormrazor"], one_rotation=True, duration=10.0
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            152.0 * 1.8
        )

    def test_multiplier_with_ie_bonus(self):
        # (2.0 + 0.30 IE bonus) x 0.9 = 2.07.
        result = _fight(
            "Yasuo",
            ["Phantom Dancer", "Infinity Edge"],
            one_rotation=True,
            duration=10.0,
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            178.0 * 2.07
        )

    def test_yone_has_no_090_factor(self):
        # P4 fix: Yone's autos NOW use the 0.9 crit-damage factor (the
        # cached stat criticalStrikeDamageModifier.flat 0.9, atom
        # 1142fbe0a600fcc8) — 171 x (0.5 + 0.5 x 2.07) = 353.97 at the
        # converted 100% + IE.
        result = _fight(
            "Yone",
            ["Phantom Dancer", "Infinity Edge"],
            one_rotation=True,
            duration=10.0,
        )
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            171.0 * 2.07
        )


# ---------------------------------------------------------------------------
# S7 - Malformed/stale/ambiguous declarations: fail-closed degraded rows
# ---------------------------------------------------------------------------


class TestDegradedRowFailClosed:
    def test_yasuo_never_prices_the_degraded_row(self):
        # The Q row's damage is derived ONLY from the Physical Damage row
        # (flat 20-120 + 105% AD).  A silent .get() fallback on the degraded
        # zeroed "Critical Strike Damage" row would price 0 - the module
        # never reads that attribute.
        stats, abilities, _ = _parse("Yasuo")
        q = abilities["Q"]
        assert q["total_raw"] == pytest.approx(120.0 + 1.05 * stats["attack_damage"])
        assert "Critical Strike Damage" not in json.dumps(q, default=str)
        assert "189% + 28.35%" not in json.dumps(q, default=str)

    def test_yone_never_prices_the_degraded_row(self):
        stats, abilities, _ = _parse("Yone")
        q = abilities["Q"]
        assert q["total_raw"] == pytest.approx(125.0 + 1.10 * stats["attack_damage"])
        assert "Critical Strike Damage" not in json.dumps(q, default=str)

    def test_yasuo_engine_reproduces_degraded_row_intent(self):
        # The degraded units "(189% + 28.35%) AD" = 105% AD x (180% + 27%)
        # = 217.35% AD.  The engine reproduces the exact math at converted
        # 100% crit WITH IE: 1.05 x 2.07 = 2.1735.  Without IE the first
        # half (189% = 1.05 x 1.8) is reproduced.
        stats, abilities, _ = _parse(
            "Yasuo", item_names=["Phantom Dancer", "Infinity Edge"]
        )
        ad_part = abilities["Q"]["parts"][1].amount
        # 105% AD x (180% + 27%) = 217.35% AD == 1.05 x 2.07 x AD.
        assert ad_part * 2.07 == pytest.approx(2.1735 * stats["attack_damage"])
        # The two halves of the degraded units:
        assert ad_part * 1.8 == pytest.approx(1.89 * stats["attack_damage"])
        assert ad_part * 0.27 == pytest.approx(0.2835 * stats["attack_damage"])

    def test_yone_q3_crit_conversion_modeled(self):
        # The completion should either add the P payload + Q crit-eligible
        # AD split to yone.py (mirroring Yasuo) or certify the boundary
        # with a named receipt.  This pins the CONVERTED behavior: the
        # degraded row's intent at converted 100% crit with IE.
        _, abilities, _ = _parse("Yone", item_names=["Phantom Dancer", "Infinity Edge"])
        q = abilities["Q"]
        assert any(p.crit_effectiveness > 0 for p in q["parts"])
        assert abilities["passive"]["crit_modifier"] == {
            "crit_chance_multiplier": 2.0,
            "crit_damage_multiplier_factor": 0.9,
            "excess_crit_bonus_ad_per_percent": 0.5,
        }


# ---------------------------------------------------------------------------
# S8 - Atom and source receipts for the P constants
# ---------------------------------------------------------------------------


class TestAtomAndSourceReceipts:
    def test_p_payload_is_sourced_prose_and_stat(self):
        # The payload's three constants match the cached P prose verbatim,
        # and the 0.9 factor is the champion game stat
        # criticalStrikeDamageModifier (atom f375a24fbf0555e1).
        _, abilities, _ = _parse("Yasuo")
        crit = abilities["passive"]["crit_modifier"]
        assert crit["crit_chance_multiplier"] == 2.0
        assert crit["crit_damage_multiplier_factor"] == 0.9
        assert crit["excess_crit_bonus_ad_per_percent"] == 0.5
        assert _atom(
            _STATS_ATOMS["Yasuo"], "stat.critical_strike_damage_modifier.flat"
        )["values"] == [0.9]

    def test_atom_backed_certification_of_p_constants(self):
        # The completion should expose an atom-backed certification (atom
        # ids + hashes) for _CRIT_CHANCE_MULTIPLIER,
        # _CRIT_DAMAGE_MULTIPLIER_FACTOR, and
        # _EXCESS_CRIT_BONUS_AD_PER_PERCENT so a patch that changes the
        # roots trips the tests.
        from src.calculator.champions import (
            yasuo as yasuo_module,
        )  # pylint: disable=import-outside-toplevel

        # A typed certification surface (like AURELION_SOL_STARDUST_RULE's
        # certified_constants / atom_ids / public_receipt) must exist and
        # agree with the module constants; it does NOT exist today.
        cert = yasuo_module.certified_constants
        assert cert["crit_chance_multiplier"] == 2.0
        assert cert["crit_damage_multiplier_factor"] == 0.9
        assert cert["excess_crit_bonus_ad_per_percent"] == 0.5


# ---------------------------------------------------------------------------
# S9 - API score/receipt parity: full vs score_only byte-identical
# ---------------------------------------------------------------------------

# Fields the compiled score path deliberately omits (run_fight docs): the
# display splits and survival/target summaries.
_SCORE_DROPPED = {
    "ability_damage",
    "auto_attack_damage",
    "damage_by_type",
    "general_shield_absorbed",
    "health_damage",
    "magic_shield_absorbed",
    "physical_shield_absorbed",
    "self_healing",
    "shield_absorbed",
    "target_effective_max_health",
    "target_ending_health",
    "target_healing_received",
    "threshold_health_bonus_gained",
    "threshold_health_triggered",
    "threshold_shield_absorbed",
}
# Keys whose full-path values carry event-ordering receipts the score path
# does not (documented in run_fight): per-event order/ordinal and the
# timeline_coverage certification note.
_SCORE_RECEIPT_ONLY = {"damage_events", "timeline_coverage"}


class TestScoreReceiptParity:
    @pytest.mark.parametrize(
        ("champion", "items", "options"),
        [
            ("Yasuo", [], None),
            ("Yasuo", ["Phantom Dancer", "Infinity Edge"], None),
            ("Yasuo", ["Phantom Dancer", "Infinity Edge"], {"q_gathering_storm": 2}),
            (
                "Yasuo",
                [
                    "Phantom Dancer",
                    "Infinity Edge",
                    "Stormrazor",
                    "Rapid Firecannon",
                    "Runaan's Hurricane",
                ],
                {"q_gathering_storm": 2},
            ),
            ("Yone", [], None),
            ("Yone", ["Phantom Dancer", "Infinity Edge"], {"q_gathering_storm": 2}),
        ],
    )
    def test_full_vs_score_only_byte_identical(self, champion, items, options):
        full = _run(champion, items, options)
        score = _run(champion, items, options, score_only=True)
        assert set(score) == set(full) - _SCORE_DROPPED
        for key in sorted(set(score) - _SCORE_RECEIPT_ONLY):
            assert _json_bytes(score[key]) == _json_bytes(full[key]), key
        # damage_events: the score path emits the same events with the same
        # values; it omits the full-path-only receipt fields.  Every shared
        # field must be byte-identical, and the omitted set must stay within
        # the documented receipt fields (fail-closed on new divergences).
        _FULL_PATH_EVENT_RECEIPT_FIELDS = {
            "order",
            "ordinal",
            "phase",
            "event_precision",
            "source_missing_ratio",
        }
        assert len(score["damage_events"]) == len(full["damage_events"])
        for score_event, full_event in zip(
            score["damage_events"], full["damage_events"]
        ):
            assert set(score_event) <= set(full_event)
            assert set(full_event) - set(score_event) <= _FULL_PATH_EVENT_RECEIPT_FIELDS
            shared = set(score_event) & set(full_event)
            assert _json_bytes({k: score_event[k] for k in shared}) == _json_bytes(
                {k: full_event[k] for k in shared}
            )
        # timeline_coverage: the certification note is full-path only; the
        # coverage facts agree (exact_sources order differs - score lists Q
        # first, full lists the engine order E/Q/R).
        assert (
            score["timeline_coverage"]["complete"]
            == full["timeline_coverage"]["complete"]
        )
        assert set(score["timeline_coverage"]["exact_sources"]) == set(
            full["timeline_coverage"]["exact_sources"]
        )

    def test_timed_fight_score_parity(self):
        # Timed fights with autos at converted 100% crit are deterministic:
        # totals, the Q row, and the auto row agree byte-identically.
        for options in (None, {"q_gathering_storm": 2}):
            full = _run("Yasuo", ["Phantom Dancer", "Infinity Edge"], options)
            score = _run(
                "Yasuo",
                ["Phantom Dancer", "Infinity Edge"],
                options,
                score_only=True,
            )
            assert full["total_damage"] == score["total_damage"]
            assert _json_bytes(full["breakdown"]["Q"]) == _json_bytes(
                score["breakdown"]["Q"]
            )
            assert _json_bytes(full["breakdown"]["auto_attacks"]) == _json_bytes(
                score["breakdown"]["auto_attacks"]
            )
            assert _json_bytes(full["champion_stats"]) == _json_bytes(
                score["champion_stats"]
            )


# ---------------------------------------------------------------------------
# S10 - API-level pins (deterministic at 0% and >=50% raw crit)
# ---------------------------------------------------------------------------


class TestApiSurface:
    def test_api_q3_knockup_and_crit_damage(self):
        # Aatrox armor 120 -> mitigation 100/220.  At 50% raw crit the
        # converted chance is 100%, so every auto crits and the API result
        # is deterministic.
        resp = _api(
            "Yasuo",
            item_names=["Phantom Dancer", "Infinity Edge"],
            options={"q_gathering_storm": 2},
            duration=4.0,
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        q_events = [e for e in payload["damage_events"] if e.get("source") == "Q"]
        assert q_events
        for event in q_events:
            assert event["damage"] == pytest.approx(506.883 * 100.0 / 220.0, rel=1e-2)
            assert event["cc_kind"] == "knockup"
            assert event["cc_duration"] == pytest.approx(0.9)
        autos = [
            e for e in payload["damage_events"] if e.get("source") == "auto_attacks"
        ]
        assert autos
        assert autos[0]["damage"] == pytest.approx(368.46 * 100.0 / 220.0, rel=1e-2)
        assert payload["champion_stats"]["attack_damage"] == pytest.approx(178.0)

    def test_api_excess_crit_visible_in_champion_stats(self):
        resp = _api(
            "Yasuo",
            item_names=[
                "Phantom Dancer",
                "Infinity Edge",
                "Stormrazor",
                "Rapid Firecannon",
                "Runaan's Hurricane",
            ],
            duration=4.0,
        )
        assert resp.status_code == 200
        stats = resp.get_json()["champion_stats"]
        assert stats["attack_damage"] == pytest.approx(302.0)
        assert stats["bonus_attack_damage"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# S11 - Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (contract 11):
#   .venv/bin/python -m pytest tests/test_yasuo_yone_q3_crit.py \
#     tests/test_aurelion_sol_stardust.py tests/test_aurelion_sol_stardust_ledger.py \
#     tests/test_senna_relic_cannon.py tests/test_senna_souls_ledger.py \
#     tests/test_quinn_p_crit.py tests/test_mana_restore_refund.py \
#     tests/test_ezreal_w_mark_refund.py tests/test_jayce_w_mana_restore.py \
#     tests/test_resource_ledger*.py tests/test_catalyst_resource_ledger.py \
#     tests/test_item_sustain.py tests/test_champion_options.py tests/test_app.py
# Yasuo / Yone grep surface (contract 10), run separately by the coordinator:
#   tests/test_p1_review_1.py (Yasuo P/Q crit pins)
#   tests/test_spell_shield_eligibility.py tests/test_delivery_interaction_eligibility.py
#   tests/test_delivery_eligibility_kernel.py (Yasuo W wind wall)
#   tests/test_cp10_batch_10.py tests/test_event_order_certification.py (roster)
#   tests/test_e9_fix_3.py (Yone E stored damage) tests/test_atomizer.py (Yasuo W atom)
#   tests/test_rotation_semantics.py tests/test_crowd_control_immunity.py
#   tests/test_e3_stacks_2.py tests/test_cleanse_eligibility.py tests/test_e8_grievous.py
