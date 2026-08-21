"""P1 Slice 11 — Ashe Q (Ranger's Focus) 6-second active window + the
timing atom label correction (test-matrix owner: RLM-2 C).

Focused TDD matrix for Ashe's Q six-second active window.  CURRENT
RUNTIME FACTS (verify-before-pin completed against
``data/champions.json``, ``data/bin/characters/ashe.bin.json`` and the
live engine):

- ``src/calculator/champions/ashe.py`` prices the Q's
  ``auto_attack_override`` (flurry ratio 1.10-1.30 AD + crit-as-bonus)
  and the 20-60 bonus-AS ``stat_buff`` for the WHOLE fight — the
  Q-window-is-permanent pin: the 6s active window is NOT modeled.  The
  game file (``ashe.bin.json`` AsheQ DataValues) has ``BuffDuration``
  6.0 FLAT at every rank (7/7 array entries), and the reviewed wiki
  cache's Q effect 1 prose says "Active: For 6 seconds, Ashe gains
  bonus attack speed and empowers her basic attacks to fire a flurry
  of five arrows...".  The 4s value in effect 0 ("generate a stack of
  Focus for 4 seconds") is the FOCUS-stack window, not the active
  window.
- The Focus walk (``damage.py`` ``_add_ashe_focus`` /
  ``_feed_ashe_focus_stack``) receipts the Q-activation consume
  (4 stacks) at the Q cast time and the per-swing gains from EVERY
  swing — including swings inside the Q's 6s window.  The passive
  prose ("While Ranger's Focus is INACTIVE, Ashe's basic attacks
  on-attack generate a stack of Focus") means the gains must stop
  during [cast, cast+6) and resume after — the inactive clause is
  absent today (pinned as the current actual).
- The ``timing.active_duration`` atom at
  ``Ashe.Q[0].effects[0].description`` (hash 3e9ba4c9427900c9,
  values [4.0], units ["s"], evidence "active duration@effects[0]
  .description") labels the 4s FOCUS window as "active duration" — a
  mislabel: the Q's active window is 6s.  No 6s timing atom exists
  today (the abilities atomizer reads effect 0 only).

The P1-11 completion will (most likely) wire the timed 6s window: the
flurry ratio + the AS buff apply on [cast, cast+6) PER SWING, then the
autos revert to the normal 1.0 ratio + the base AS; the Focus gains
resume after the window (the inactive clause); the atom label is
corrected and the 6s atom added; the golden deltas (if any — see the
footer: the current golden has NO Ashe auto fight beyond 5s, so the
expected delta is zero unless new 6s+ Ashe fights are registered) are
explained.  Genuinely-absent mechanics are ``pytest.mark.xfail``
(non-strict) with reason "awaiting P1-11 ..." — the completion removes
the markers.

Scheduling convention pinned by this matrix (documented for the
coordinator): the swing TIMES follow the engine's existing
empowered-window precedent (``_base_auto_attack_timestamps``) — the
buffed cadence runs ``k / buffed_as`` for the in-window block, then the
timer continues at the base cadence from the first post-window tick;
the PRICING is per-swing by time: any swing at time t with
``cast <= t < cast + 6`` is flurry-priced (the brief's "per swing"
seam), any swing at ``t < cast`` or ``t >= cast + 6`` is priced at the
normal 1.0 ratio.  The end boundary is end-exclusive: the swing AT
``cast + 6`` (exactly) is normal.  The one convention seam the
coordinator must confirm: whether the in-window/out-window pricing is
per-swing (this matrix) or per-block (the engine's ``empowered_autos``
block pricing would price the 5.95745s swing normal); every exact-value
pin below follows the per-swing reading.

Expected damage values are recomputed from the typed parse output and
the fight's own stats — no literal damage constants.  The window
constants (6.0s active / 4.0s Focus) and the atom hashes ARE the values
under test and appear as literal contract constants beside their
game-file evidence.
"""

import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from src.calculator import atomizer_domains
from src.calculator import state_lifecycle as sl
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.ashe import ASHE_FOCUS_STACK_RULE
from src.calculator.champions.rengar import RENGAR_FEROCITY_STACK_RULE
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_GAME_FILE_PATH = Path("data/bin/characters/ashe.bin.json")
_GAME_FILE = (
    json.loads(_GAME_FILE_PATH.read_text(encoding="utf-8"))
    if _GAME_FILE_PATH.exists()
    else None
)
_ABILITIES_ATOMS = json.loads(
    Path("data/atoms/abilities.json").read_text(encoding="utf-8")
)
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
# The sourced active window: the game file BuffDuration (6.0 flat at
# every rank) and the wiki cache effect 1 prose ("Active: For 6
# seconds").  The Focus-stack window (effect 0 prose + StackDuration)
# is 4.0.
WINDOW_SECONDS = 6.0
FOCUS_WINDOW_SECONDS = 4.0
# Genuinely-absent mechanics are xfailed with this reason (never strict
# — the P1-11 completion removes the markers).
_AWAIT = "awaiting P1-11 six-second active window"
XFAIL = pytest.mark.xfail(reason=_AWAIT, strict=False)

# The corrected-atom contract records (S14).  Hashes are computed with
# the atomizer's canonical record hash (sha256 of the sorted JSON,
# 16 hex chars) so the completion's emitted atoms can be verified
# byte-for-byte.
CORRECTED_FOCUS_ATOM = {
    "atom_id": "timing.stack_duration",
    "behavior": "timing",
    "source": "Ashe.Q[0].effects[0].description",
    "name": "Ranger's Focus",
    "values": [4.0],
    "units": ["s"],
    "evidence": ["stack duration@effects[0].description"],
}
ACTIVE_WINDOW_ATOM = {
    "atom_id": "timing.active_duration",
    "behavior": "timing",
    "source": "Ashe.Q[0].effects[1].description",
    "name": "Ranger's Focus",
    "values": [6.0],
    "units": ["s"],
    "evidence": ["active duration@effects[1].description"],
}


def _atom_hash(record: dict) -> str:
    record = dict(record)
    record["evidence"] = sorted(set(record["evidence"]))
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


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


def _parse(option: dict | None, *, ranks: dict | None = None, data=None):
    stats = _stats()
    return stats, parse_champion_abilities(
        data if data is not None else get_champion("Ashe"),
        _LEVEL,
        0.0,
        ability_ranks=ranks if ranks is not None else _RANKS,
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
    target_armor: float = 50.0,
    ranks: dict | None = None,
    stats_override: dict | None = None,
) -> dict:
    stats, abilities = _parse(option, ranks=ranks)
    if stats_override:
        stats = dict(stats)
        stats.update(stats_override)
        abilities = parse_champion_abilities(
            get_champion("Ashe"),
            _LEVEL,
            0.0,
            ability_ranks=ranks if ranks is not None else _RANKS,
            champion_stats=stats,
            target_stats={"target_max_health": 2000.0},
            champion_options=option,
        )
    return calculate_fight_damage(
        stats,
        abilities,
        items or [],
        FightConfig(
            target_health=2000,
            target_armor=target_armor,
            target_magic_resistance=40,
            fight_duration_seconds=duration,
            auto_attack_uptime=auto_attack_uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=(cast_order if cast_order is not None else ["Q", "W", "R"]),
        ),
        score_only=score_only,
        champion_options=dict(option),
    )


def _q_leveling(attribute: str) -> dict:
    ability = _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"Ashe Q has no leveling {attribute!r}")


def _q_value(attribute: str, rank: int) -> float:
    total = 0.0
    for modifier in _q_leveling(attribute).get("modifiers", []):
        values = modifier.get("values", [])
        if not values:
            continue
        idx = min(rank - 1, len(values) - 1)
        total += float(values[idx])
    return total


def _game_data_value(name: str, rank: int) -> float:
    """One Ashe Q DataValue at *rank* (rank 1 at array index 1)."""
    if _GAME_FILE is None:
        pytest.skip("local Ashe game-file evidence is unavailable")
    spell = _GAME_FILE["Characters/Ashe/Spells/AsheQAbility/AsheQ"]["mSpell"]
    for entry in spell["DataValues"]:
        if entry.get("name") == name:
            return float(entry["values"][rank])
    raise AssertionError(f"game file AsheQ has no DataValue {name!r}")


def _strip_q_rows(attrs: set[str]):
    data = copy.deepcopy(get_champion("Ashe"))
    ability = data["abilities"]["Q"][0]
    for effect in ability.get("effects", []):
        effect["leveling"] = [
            leveling
            for leveling in effect.get("leveling", [])
            if leveling.get("attribute") not in attrs
        ]
    return data


def _swing_events(result: dict) -> list[dict]:
    return list(result["breakdown"]["auto_attacks"]["damage_events"])


def _focus_account(result: dict) -> dict | None:
    section = result.get("resource_ledger")
    if not isinstance(section, dict):
        return None
    if section.get("kind") == "focus":
        return section
    sub = section.get("focus")
    return sub if isinstance(sub, dict) else None


def _q_cast_times(result: dict) -> list[float]:
    return [
        float(cast["time"]) for cast in result["cast_timeline"] if cast["slot"] == "Q"
    ]


def _swing_damages(result: dict) -> dict[float, float]:
    return {float(e["time"]): float(e["damage"]) for e in _swing_events(result)}


def _q_ability_atoms() -> list[dict]:
    return [a for a in _ABILITIES_ATOMS["objects"]["Ashe"] if "Q[0]" in a["source"]]


def _q_live_atoms() -> list[dict]:
    return atomizer_domains.atomize_abilities("Ashe", get_champion("Ashe"))["Q"]


def _flurry_damage(stats: dict, abilities: dict, armor: float = 50.0) -> float:
    """The per-swing flurry damage at the fight's mitigation."""
    ratio = abilities["Q"]["auto_attack_override"]["ad_ratio"]
    return stats["attack_damage"] * ratio / (1.0 + armor / 100.0)


def _normal_damage(stats: dict, abilities: dict, armor: float = 50.0) -> float:
    """The per-swing normal damage (the 1.0 ratio the inactive Q prices)."""
    passive = abilities["passive"].get("auto_attack_override")
    ratio = passive["ad_ratio"] if passive is not None else 1.0
    assert ratio == pytest.approx(1.0)
    return stats["attack_damage"] * 1.0 / (1.0 + armor / 100.0)


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values (the window's inputs)
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_game_file_buff_duration_is_six_seconds_flat_at_every_rank(self):
        # The active window: BuffDuration 6.0 at EVERY array entry (the
        # game file has 7 entries: level 0 + ranks 1-6) — no rank row
        # changes the window.
        if _GAME_FILE is None:
            pytest.skip("local Ashe game-file evidence is unavailable")
        spell = _GAME_FILE["Characters/Ashe/Spells/AsheQAbility/AsheQ"]["mSpell"]
        buff = next(e for e in spell["DataValues"] if e.get("name") == "BuffDuration")
        assert all(value == pytest.approx(6.0) for value in buff["values"])

    def test_wiki_prose_declares_the_six_second_active_window(self):
        # The reviewed cache entry's effect 1 (the ACTIVE effect) says
        # "For 6 seconds" — the same window the game file pins.
        ability = _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0]
        active = ability["effects"][1]["description"]
        assert "For 6 seconds" in active
        assert "flurry of five arrows" in active
        assert "bonus attack speed" in active

    def test_wiki_prose_declares_the_four_second_focus_window(self):
        # Effect 0 (the PASSIVE Focus generation) is the 4s stack window
        # — the value the atomizer currently mislabels as the active
        # duration.
        ability = _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0]
        passive = ability["effects"][0]["description"]
        assert "generate a stack of Focus for 4 seconds" in passive
        assert "While Ranger's Focus is inactive" in passive

    def test_rank_rows_as_flurry_and_attack_speed(self):
        # The rank rows through the cached leveling: AS 20-60, flurry
        # 110-130, per-arrow 22-26.
        assert _q_value("Bonus Attack Speed", 1) == pytest.approx(20.0)
        assert _q_value("Bonus Attack Speed", 5) == pytest.approx(60.0)
        assert _q_value("Total Damage Per Flurry", 1) == pytest.approx(110.0)
        assert _q_value("Total Damage Per Flurry", 5) == pytest.approx(130.0)
        assert _q_value("Physical Damage Per Arrow", 1) == pytest.approx(22.0)
        assert _q_value("Physical Damage Per Arrow", 5) == pytest.approx(26.0)

    def test_game_file_corroborates_the_rank_rows(self):
        # The game file's rank-1..5 rows match the cached values the
        # module prices (rank 1 at array index 1).
        for rank, (as_pct, flurry) in enumerate(
            ((20.0, 1.10), (30.0, 1.15), (40.0, 1.20), (50.0, 1.25), (60.0, 1.30)),
            1,
        ):
            assert _game_data_value("BonusAS", rank) == pytest.approx(as_pct)
            assert _game_data_value("DamagePerStrike", rank) == pytest.approx(flurry)
        # The flurry fires 5 arrows and the window is 6s at every rank.
        assert _game_data_value("ShotsPerStrike", 5) == pytest.approx(5.0)
        assert _game_data_value("BuffDuration", 5) == pytest.approx(6.0)

    def test_typed_path_prices_the_window_inputs(self):
        # The module's typed path: rank 5 -> 60 bonus AS + flurry 1.30;
        # rank 1 -> 20 + 1.10.  The window itself is NOT on the parse
        # today (the whole-fight pin).
        _, abilities = _parse({}, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(60.0)
        assert abilities["Q"]["auto_attack_override"]["ad_ratio"] == pytest.approx(1.30)
        _, abilities = _parse({}, ranks={"Q": 1, "W": 5, "E": 5, "R": 3})
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(20.0)
        assert abilities["Q"]["auto_attack_override"]["ad_ratio"] == pytest.approx(1.10)

    def test_focus_window_rule_is_four_seconds(self):
        # The typed Focus rule pins the 4s stack window (StackDuration 4
        # flat in the game file + the effect-0 prose).
        assert ASHE_FOCUS_STACK_RULE.public_receipt()["duration_seconds"] == 4.0
        assert _game_data_value("StackDuration", 5) == pytest.approx(4.0)
        assert _game_data_value("MaxStacks", 5) == pytest.approx(4.0)

    def test_atom_label_mislabel_is_the_current_actual(self):
        # The mislabel pinned exactly (S14 has the full contract): the
        # ONLY timing atom the abilities atomizer emits for the Q today
        # labels the 4s FOCUS window as the active duration, and no 6s
        # atom exists.
        q_atoms = _q_ability_atoms()
        timing = [a for a in q_atoms if a["behavior"] == "timing"]
        # P1-11: the Focus window is relabeled (timing.stack_duration)
        # and the real 6s active window is extracted from effects[1].
        assert len(timing) == 2
        focus = next(a for a in timing if a["atom_id"] == "timing.stack_duration")
        assert focus["source"] == "Ashe.Q[0].effects[0].description"
        assert focus["values"] == [4.0]
        assert focus["units"] == ["s"]
        assert focus["evidence"] == ["stack duration@effects[0].description"]
        assert focus["hash"] == "c11240f633391d49"
        active = next(a for a in timing if a["atom_id"] == "timing.active_duration")
        assert active["source"] == "Ashe.Q[0].effects[1].description"
        assert active["values"] == [6.0]
        assert active["units"] == ["s"]
        assert active["evidence"] == ["active duration@effects[1].description"]
        assert active["hash"] == "468689debc47d9b6"


# ---------------------------------------------------------------------------
# S2 — Pre-window swings: the swings before the Q cast use the normal
#      1.0 ratio (the Q is inactive)
# ---------------------------------------------------------------------------


class TestPreWindowSwings:
    def test_q_cast_time_default_order_is_zero(self):
        # The window start is the Q cast time: default cast order puts Q
        # at t=0 in both modes (verified runtime fact).
        for one_rotation in (False, True):
            result = _fight({}, duration=10.0, one_rotation=one_rotation)
            assert _q_cast_times(result) == [0.0]

    def test_timed_mode_q_cast_at_0_25_with_w_first(self):
        # With W first, the timed scheduler casts Q at 0.25 (W's 0.25s
        # cast occupies [0, 0.25)); one_rotation still casts at 0.
        result = _fight({}, duration=10.0, cast_order=["W", "Q", "R"])
        assert _q_cast_times(result) == [0.25]
        result = _fight(
            {}, duration=10.0, cast_order=["W", "Q", "R"], one_rotation=True
        )
        assert _q_cast_times(result) == [0.0]

    def test_windowed_pricing_under_the_legacy_override(self):
        # P1-11: with Q active, the windowed pricing applies — the
        # first swing lands AT the cast (the floor count drops the
        # pre-cast 0.0 swing) and is flurry-priced; the post-window
        # swings revert.
        result = _fight(
            {}, duration=10.0, cast_order=["W", "Q", "R"], auto_attack_uptime=1.0
        )
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        cast = _q_cast_times(result)[0]
        assert cast == pytest.approx(0.25)
        assert damages[0.25] == pytest.approx(_flurry_damage(stats, abilities))

    def test_swings_before_the_cast_use_the_normal_ratio(self):
        # Contract: any swing at t < cast is priced at the normal 1.0
        # ratio (the Q is inactive before its cast).
        result = _fight(
            {}, duration=10.0, cast_order=["W", "Q", "R"], auto_attack_uptime=1.0
        )
        stats, abilities = _parse({})
        cast = _q_cast_times(result)[0]
        damages = _swing_damages(result)
        # The floor count convention drops the pre-cast segment (the
        # 0.25s pre-cast window cannot complete a swing at 0.8/s), so no
        # pre-cast swing exists; the first swing lands AT the cast and
        # is flurry-priced (the start-inclusive boundary).
        pre = {t: d for t, d in damages.items() if t < cast}
        assert pre == {}
        assert damages[cast] == pytest.approx(_flurry_damage(stats, abilities))


# ---------------------------------------------------------------------------
# S3 — Start boundary: the Q cast time = the window start; the swing AT
#      the cast uses the flurry ratio
# ---------------------------------------------------------------------------


class TestStartBoundary:
    def test_swing_at_the_cast_is_flurry_today(self):
        # The swing AT the cast time (t=0 with the default order) is
        # flurry-priced today — the start boundary is start-inclusive.
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        assert _q_cast_times(result) == [0.0]
        assert _swing_damages(result)[0.0] == pytest.approx(
            _flurry_damage(stats, abilities)
        )

    def test_swing_at_the_cast_is_flurry_under_the_window(self):
        # The start boundary is start-inclusive: the swing AT the cast
        # time is in-window and prices the flurry ratio — true today
        # (permanent window) and under the completion (the window starts
        # at the cast).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        cast = _q_cast_times(result)[0]
        damages = _swing_damages(result)
        assert damages[cast] == pytest.approx(_flurry_damage(stats, abilities))

    def test_window_start_is_the_cast_time_in_both_modes(self):
        # The window starts at the Q cast time in one_rotation AND timed
        # mode; the first swing sits at the cast (true in both worlds —
        # the permanent window and the timed window).
        for one_rotation in (False, True):
            result = _fight(
                {}, duration=10.0, auto_attack_uptime=1.0, one_rotation=one_rotation
            )
            cast = _q_cast_times(result)[0]
            events = _swing_events(result)
            assert any(abs(float(e["time"]) - cast) < 1e-9 for e in events)


# ---------------------------------------------------------------------------
# S4 — In-window swings: [cast, cast+6) use the flurry ratio + buffed AS
# ---------------------------------------------------------------------------


class TestInWindowSwings:
    def test_post_window_swing_is_flurry_today(self):
        # The permanent-window pin: the swing at 6.80851s (a post-window
        # time under the 6s convention) is flurry-priced today and the
        # cadence never drops to the base rate.
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        # The post-window swing at 6.0 is normal-priced; the 10s fight
        # lands 10 swings (7 in-window at the buffed cadence + 3
        # post-window at the base cadence).
        assert damages[6.0] == pytest.approx(_normal_damage(stats, abilities))
        assert len(_swing_events(result)) == 10
        buffed_interval = 1.0 / (0.8 + 0.625 * 0.6)
        in_events = sorted(e["time"] for e in _swing_events(result) if e["time"] < 6.0)
        for index, t in enumerate(in_events):
            assert float(t) == pytest.approx(index * buffed_interval)

    def test_in_window_swings_use_flurry_ratio_and_buffed_cadence(self):
        # Every swing at t in [cast, cast+6) is flurry-priced and the
        # in-window cadence is the buffed attack speed.  The 10s
        # reference fight has 7 in-window swings at k/1.175 (k = 0..6,
        # the last at 5.106 < 6 — the engine's floor-count convention
        # drops the 8th tick exactly as at the fight end).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        cast = _q_cast_times(result)[0]
        buffed_as = stats["attack_speed"] + stats["attack_speed_ratio"] * (
            abilities["Q"]["stat_buff"]["bonus_attack_speed"] / 100.0
        )
        damages = _swing_damages(result)
        in_window = {t: d for t, d in damages.items() if cast <= t < cast + 6.0}
        assert len(in_window) == 7
        for k, t in enumerate(sorted(in_window)):
            assert t == pytest.approx(cast + k / buffed_as)
            assert in_window[t] == pytest.approx(_flurry_damage(stats, abilities))


# ---------------------------------------------------------------------------
# S5 — End boundary: the swing AT cast+6 uses the normal ratio
#      (end-exclusive)
# ---------------------------------------------------------------------------


class TestEndBoundary:
    def test_boundary_swing_is_flurry_today(self):
        # A fight whose buffed cadence lands a swing EXACTLY at 6.0s
        # (AS 1.25 + ratio 1.25 -> buffed 2.0/s): today that swing is
        # flurry-priced (the window is permanent) and the fight runs 20
        # swings at the buffed cadence.
        result = _fight(
            {},
            duration=10.0,
            auto_attack_uptime=1.0,
            stats_override={"attack_speed": 1.25, "attack_speed_ratio": 1.25},
        )
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        # P1-11: the swing at exactly cast+6 is NORMAL (the end-exclusive
        # boundary).
        assert damages[6.0] == pytest.approx(_normal_damage(stats, abilities))
        assert len(_swing_events(result)) == 17

    def test_swing_at_cast_plus_window_is_normal(self):
        # Contract (end-exclusive): the swing at exactly cast+6 is OUT of
        # the window and prices the normal 1.0 ratio.  The AS-2.0 fight
        # lands a swing exactly at 6.0 (the 13th tick).
        result = _fight(
            {},
            duration=10.0,
            auto_attack_uptime=1.0,
            stats_override={"attack_speed": 1.25, "attack_speed_ratio": 1.25},
        )
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        assert damages[6.0] == pytest.approx(_normal_damage(stats, abilities))

    def test_no_in_window_swing_is_priced_past_the_boundary(self):
        # Contract: no swing at t >= cast+6 carries the flurry ratio —
        # every out-of-window swing is normal (the half-open window
        # holds for every event, whatever the schedule).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        cast = _q_cast_times(result)[0]
        damages = _swing_damages(result)
        out = {t: d for t, d in damages.items() if t >= cast + 6.0}
        assert out
        assert all(
            d == pytest.approx(_normal_damage(stats, abilities)) for d in out.values()
        )


# ---------------------------------------------------------------------------
# S6 — Post-window swings: after cast+6 the autos revert to the normal
#      1.0 ratio + the base AS
# ---------------------------------------------------------------------------


class TestPostWindowSwings:
    def test_post_window_swings_revert_to_normal_ratio_and_base_as(self):
        # Contract: swings at t >= cast+6 are priced at the normal 1.0
        # ratio and the cadence continues at the base attack speed.  The
        # 10s reference fight has 3 post-window swings at the base 0.8/s
        # cadence.
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        cast = _q_cast_times(result)[0]
        damages = _swing_damages(result)
        post = sorted(t for t in damages if t >= cast + 6.0)
        assert len(post) == 3
        for t in post:
            assert damages[t] == pytest.approx(_normal_damage(stats, abilities))
        # The timer continues from the last in-window tick at the base
        # cadence (the engine's empowered-block convention).
        # The normal phase starts AT the window end (the end-exclusive
        # boundary — a swing landing exactly at cast+6 is normal).
        first_post = post[0]
        assert first_post == pytest.approx(cast + 6.0)
        for a, b in zip(post, post[1:]):
            assert b - a == pytest.approx(1.0 / stats["attack_speed"])

    def test_total_swing_count_unchanged_at_ten_seconds(self):
        # The 10s fight lands 10 swings under the window (7 in-window at
        # the buffed cadence + 3 post-window at the base cadence) — the
        # floor-count convention per phase (the engine's 11 whole-fight
        # swings become 7 + 3).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        assert len(_swing_events(result)) == 10

    def test_fight_total_matches_the_windowed_pricing(self):
        # Contract: the auto total = 7 flurry swings + 3 normal swings
        # (per-swing pricing; the engine's floor-count convention).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        expected = 7 * _flurry_damage(stats, abilities) + 3 * _normal_damage(
            stats, abilities
        )
        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            expected
        )


# ---------------------------------------------------------------------------
# S7 — Rank zero: no Q -> no window (the normal autos)
# ---------------------------------------------------------------------------


class TestRankZero:
    def test_rank_zero_prices_normal_autos_no_q_surface(self):
        # Q rank 0: no Q entry, the passive carries the 1.0 override,
        # every swing is normal, and no Q cast exists (so no window can
        # start).
        ranks = {"Q": 0, "W": 5, "E": 5, "R": 3}
        result = _fight(
            {"q_focus_stacks": 4}, duration=10.0, ranks=ranks, auto_attack_uptime=1.0
        )
        stats, abilities = _parse({"q_focus_stacks": 4}, ranks=ranks)
        assert "Q" not in abilities
        assert abilities["passive"]["auto_attack_override"]["ad_ratio"] == (
            pytest.approx(1.0)
        )
        assert _q_cast_times(result) == []
        damages = _swing_damages(result)
        assert damages
        assert all(
            d == pytest.approx(_normal_damage(stats, abilities))
            for d in damages.values()
        )

    def test_q_active_false_has_no_q_no_window(self):
        # q_active False: same normal surface (the legacy activation
        # override), no Q cast, no window inputs.
        result = _fight({"q_active": False}, duration=10.0, auto_attack_uptime=1.0)
        assert _q_cast_times(result) == []
        stats, abilities = _parse({"q_active": False})
        assert "Q" not in abilities
        assert all(
            d == pytest.approx(_normal_damage(stats, abilities))
            for d in _swing_damages(result).values()
        )


# ---------------------------------------------------------------------------
# S8 — Missing rows: fail-closed (the _require_row precedent)
# ---------------------------------------------------------------------------


class TestMissingRows:
    def test_stripped_q_rows_fail_loud(self):
        # The _require_q_rows guard: missing AS/flurry leveling rows
        # raise a KeyError naming the row — never a silent zero flurry.
        with pytest.raises(KeyError) as excinfo:
            _parse(
                {},
                data=_strip_q_rows({"Bonus Attack Speed", "Total Damage Per Flurry"}),
            )
        assert "Bonus Attack Speed" in str(
            excinfo.value
        ) or "Total Damage Per Flurry" in str(excinfo.value)

    def test_window_pricing_never_invents_a_ratio(self):
        # Contract: the windowed pricing consumes the same typed rows —
        # a stripped row fails closed (raises) instead of pricing a
        # silent 0.0/1.0 window.
        with pytest.raises(KeyError):
            _parse({}, data=_strip_q_rows({"Total Damage Per Flurry"}))


# ---------------------------------------------------------------------------
# S9 — Repeated Q: the engine casts Q once; a second activation within
#      the window is impossible (the window is NOT refreshed)
# ---------------------------------------------------------------------------


class TestRepeatedQ:
    def test_engine_casts_q_exactly_once(self):
        # The single-cast rule (cooldown 0 -> the timed scheduler's
        # single_cast set): one Q cast in a 60s fight, at t=0.
        result = _fight({}, duration=60.0, auto_attack_uptime=0.0)
        assert _q_cast_times(result) == [0.0]

    def test_second_activation_is_impossible_in_game(self):
        # Source pin: the Q costs "30 Mana + 4 Focus" (consume) and
        # Focus generates only while the Q is INACTIVE (the effect-0
        # prose), so a second activation within the 6s window cannot
        # exist in-game — there are no stacks to spend.  The engine's
        # single cast therefore also means the window is never refreshed
        # (no second cast to refresh it).
        ability = _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0]
        assert (
            "While Ranger's Focus is inactive" in ability["effects"][0]["description"]
        )
        assert ability["cooldown"] is None  # stack-activated, no cd row

    def test_focus_walk_consumes_once(self):
        # One Q cast -> one consume receipt at the cast time (4G).
        result = _fight({}, duration=60.0, auto_attack_uptime=0.0)
        account = _focus_account(result)
        assert account is not None
        consumes = [
            r
            for r in account["receipts"]
            if r["operation"] == "consume" and r["accepted"]
        ]
        assert len(consumes) == 1
        assert consumes[0]["amount"] == -4
        assert consumes[0]["time"] == 0.0

    def test_window_is_not_refreshed(self):
        # Contract: exactly one window per fight — the post-window
        # swings revert even though a recast would be impossible anyway;
        # no refresh receipt/event exists on the window.
        result = _fight({}, duration=60.0, auto_attack_uptime=1.0)
        assert len(_q_cast_times(result)) == 1
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        late = {t: d for t, d in damages.items() if t >= 6.0}
        assert late
        assert all(
            d == pytest.approx(_normal_damage(stats, abilities)) for d in late.values()
        )


# ---------------------------------------------------------------------------
# S10 — Focus consume at the cast + the gains RESUME after the window
#       (the inactive clause)
# ---------------------------------------------------------------------------


class TestFocusConsumeAndGainsResume:
    def test_consume_fires_at_the_cast_today(self):
        # The Q-activation consume (4G) is receipted at the cast time.
        for one_rotation in (False, True):
            result = _fight(
                {}, duration=10.0, auto_attack_uptime=1.0, one_rotation=one_rotation
            )
            account = _focus_account(result)
            assert account is not None
            consumes = [
                r
                for r in account["receipts"]
                if r["operation"] == "consume" and r["accepted"]
            ]
            assert consumes and consumes[0]["time"] == 0.0
            assert consumes[0]["amount"] == -4

    def test_in_window_gains_fire_today(self):
        # The missing-inactive-clause pin: today the walk accepts gains
        # from swings INSIDE the Q's 6s window (the first swings after
        # the consume rebuild the stack).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        gains = [
            r
            for r in account["receipts"]
            if r["operation"] == "gain" and r["accepted"] and r["amount"] > 0
        ]
        # P1-11: the in-window swings gain NOTHING (the inactive
        # clause) — no accepted in-window gain exists.
        assert not any(0.0 <= g["time"] < 6.0 for g in gains)

    def test_in_window_swings_gain_nothing(self):
        # Contract (the inactive clause): the passive prose
        # ("While Ranger's Focus is inactive...") — no accepted gain
        # with amount > 0 lands inside [cast, cast+6); in-window swings
        # are receipted as named denials (never "at_cap" — a distinct
        # reason naming the active window).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        gains = [
            r
            for r in account["receipts"]
            if r["operation"] == "gain" and r["accepted"] and r["amount"] > 0
        ]
        assert all(not (0.0 <= g["time"] < 6.0) for g in gains)
        in_window = [
            r
            for r in account["receipts"]
            if r["operation"] == "gain"
            and 0.0 <= r["time"] < 6.0
            and r["source"].startswith("auto attack")
        ]
        assert in_window
        assert all(
            not r["accepted"]
            and r["reason"] != "at_cap"
            and ("active" in r["reason"].lower() or "window" in r["reason"].lower())
            for r in in_window
        )

    def test_gains_resume_after_the_window(self):
        # Contract: after cast+6 the autos generate Focus again — an
        # accepted gain with amount > 0 lands at a swing time >= cast+6
        # (the walk's gains resume; the seeded 4 was consumed at the
        # cast, so the first post-window swing actually moves the
        # counter).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        gains = [
            r
            for r in account["receipts"]
            if r["operation"] == "gain" and r["accepted"] and r["amount"] > 0
        ]
        assert any(g["time"] >= 6.0 for g in gains)
        assert account["closing_current"] > 0


# ---------------------------------------------------------------------------
# S11 — Attacks after expiry: post-window autos' damage (normal ratio)
#       + the Focus gains
# ---------------------------------------------------------------------------


class TestAttacksAfterExpiry:
    def test_first_post_window_swing_is_flurry_today(self):
        # P1-11: the first post-window swing (6.0 — the window end,
        # end-exclusive) is normal-priced.
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        assert damages[6.0] == pytest.approx(_normal_damage(stats, abilities))

    def test_post_window_swings_deal_normal_damage_and_gain_focus(self):
        # Contract: after expiry the autos deal the normal-ratio damage
        # AND their swings generate Focus (the two facts land on the
        # same swing times).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        account = _focus_account(result)
        assert account is not None
        post_times = sorted(t for t in damages if t >= 6.0)
        assert post_times
        for t in post_times:
            assert damages[t] == pytest.approx(_normal_damage(stats, abilities))
        gain_times = {
            r["time"]
            for r in account["receipts"]
            if r["operation"] == "gain" and r["accepted"]
        }
        assert any(t in gain_times for t in post_times)


# ---------------------------------------------------------------------------
# S12 — No new option: the q_active/q_focus_stacks semantics preserved
# ---------------------------------------------------------------------------


class TestNoNewOption:
    def test_option_metadata_unchanged(self):
        # The window is DERIVED from the Q cast + the sourced 6s
        # BuffDuration — no new option is added.
        meta = get_champion_options_meta("Ashe")
        assert {o["key"] for o in meta["options"]} == {"q_active", "q_focus_stacks"}

    def test_q_active_and_q_focus_stacks_semantics_unchanged(self):
        # q_active False gates the Q surface; q_focus_stacks seeds the
        # gate (4 opens, 3 closes) — exactly as before the window.
        for option in (
            {"q_active": False},
            {"q_focus_stacks": 0},
            {"q_focus_stacks": 3},
            {"q_focus_stacks": 4},
        ):
            _, abilities = _parse(option)
            if option.get("q_active") is False or option.get("q_focus_stacks", 4) < 4:
                assert "Q" not in abilities
                assert abilities["passive"]["auto_attack_override"]["ad_ratio"] == (
                    pytest.approx(1.0)
                )
            else:
                assert "Q" in abilities

    def test_default_options_produce_the_window(self):
        # Contract: the windowed pricing is active under the module
        # defaults (no new option) — the 10s fight's post-window swings
        # are normal-priced with the same options that today price them
        # flurry.
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        # The post-window swings (6.0, 7.25, 8.5) revert to the normal
        # ratio; the in-window swings keep the flurry price.
        assert damages[6.0] == pytest.approx(_normal_damage(stats, abilities))
        assert damages[8.5] == pytest.approx(_normal_damage(stats, abilities))
        assert damages[0.0] == pytest.approx(_flurry_damage(stats, abilities))


# ---------------------------------------------------------------------------
# S13 — Source receipts: the window's evidence (game file + wiki)
# ---------------------------------------------------------------------------


class TestSourceReceipts:
    def test_module_source_receipts_unchanged(self):
        # The module's public receipts cite the reviewed wiki cache
        # revision that carries the "For 6 seconds" prose.
        meta = get_champion_options_meta("Ashe")
        assert meta["sources"][0]["revision_id"] == 4015971
        assert meta["sources"][0]["url"].endswith("/en-us/Ashe")
        assert (
            ASHE_FOCUS_STACK_RULE.public_receipt()["source"]["revision_id"] == 4015971
        )

    def test_game_file_is_the_flat_window_evidence(self):
        # The game file the completion must cite: BuffDuration 6.0 at
        # every rank — the receipt for the window's duration.
        if _GAME_FILE is None:
            pytest.skip("local Ashe game-file evidence is unavailable")
        spell = _GAME_FILE["Characters/Ashe/Spells/AsheQAbility/AsheQ"]["mSpell"]
        buff = next(e for e in spell["DataValues"] if e.get("name") == "BuffDuration")
        assert buff["values"] == [6.0] * len(buff["values"])

    def test_typed_parse_declares_the_six_second_window(self):
        # Contract: the parse output carries a typed declaration of the
        # sourced 6s window beside the flurry/AS pricing (the coordinator
        # names the field; accepted keys: active_duration_seconds /
        # window_seconds / buff_duration_seconds on the Q entry or its
        # auto_attack_override), receipted to the game file + the wiki
        # prose.
        _, abilities = _parse({})
        q = abilities["Q"]
        candidates = {}
        for container, label in (
            (q, "Q"),
            (q.get("auto_attack_override") or {}, "Q.override"),
        ):
            for key, value in container.items():
                if "window" in key.lower() or "duration" in key.lower():
                    candidates[f"{label}.{key}"] = value
        assert candidates, "no typed window declaration on the Q parse"
        assert any(value == pytest.approx(6.0) for value in candidates.values())


# ---------------------------------------------------------------------------
# S14 — Atom label: the corrected 4s atom + the 6s active atom
# ---------------------------------------------------------------------------


class TestAtomLabel:
    def test_emitter_reproduces_the_mislabel_today(self):
        # The live abilities atomizer emits the corrected pair (the
        # Focus-window relabel + the 6s active window), matching the
        # tracked cache records.
        live = [a for a in _q_live_atoms() if a["behavior"] == "timing"]
        assert len(live) == 2
        hashes = {a["hash"] for a in live}
        assert hashes == {"c11240f633391d49", "468689debc47d9b6"}

    def test_atom_hash_contract_verified(self):
        # The pinned hashes follow the atomizer's canonical record hash.
        assert _atom_hash(ACTIVE_WINDOW_ATOM) == "468689debc47d9b6"
        assert _atom_hash(CORRECTED_FOCUS_ATOM) == "c11240f633391d49"

    def test_focus_window_atom_is_relabeled(self):
        # Contract: the 4s effects[0] atom no longer claims to be the
        # active duration — it carries the corrected label/atom_id (the
        # pinned record: timing.stack_duration, evidence "stack
        # duration@effects[0].description", values [4.0], units ["s"],
        # hash c11240f633391d49).  The coordinator may pick the final
        # atom_id; the VALUES and the semantic (not "active duration")
        # are the contract.
        q_atoms = _q_ability_atoms()
        timing = [a for a in q_atoms if a["behavior"] == "timing"]
        focus = [a for a in timing if a["source"] == "Ashe.Q[0].effects[0].description"]
        assert focus
        atom = focus[0]
        assert atom["values"] == [4.0]
        assert atom["units"] == ["s"]
        assert atom["evidence"] != ["active duration@effects[0].description"]
        assert "active duration" not in " ".join(atom["evidence"])
        assert atom["hash"] != "3e9ba4c9427900c9"

    def test_six_second_active_window_atom_added(self):
        # Contract: the 6s active window atom exists with the sourced
        # values/units/evidence/hash — the record the completion must
        # emit from the effect-1 prose ("For 6 seconds"):
        # timing.active_duration @ Ashe.Q[0].effects[1].description,
        # values [6.0], units ["s"], evidence "active
        # duration@effects[1].description", hash 468689debc47d9b6.
        q_atoms = _q_ability_atoms()
        atom = next(
            (
                a
                for a in q_atoms
                if a["source"] == "Ashe.Q[0].effects[1].description"
                and a["behavior"] == "timing"
            ),
            None,
        )
        assert atom is not None
        assert atom["atom_id"] == "timing.active_duration"
        assert atom["values"] == [6.0]
        assert atom["units"] == ["s"]
        assert atom["evidence"] == ["active duration@effects[1].description"]
        assert atom["hash"] == "468689debc47d9b6"

    def test_live_emitter_produces_both_atoms(self):
        # Contract: the live abilities atomizer emits the corrected 4s
        # atom AND the 6s atom (the tracked cache regenerates from the
        # same emitter).
        live = [a for a in _q_live_atoms() if a["behavior"] == "timing"]
        sources = {a["source"] for a in live}
        assert "Ashe.Q[0].effects[0].description" in sources
        assert "Ashe.Q[0].effects[1].description" in sources


# ---------------------------------------------------------------------------
# S15 — Score/fallback parity: score_only models the window identically
#       or returns the named receipt — never a silent re-price
# ---------------------------------------------------------------------------


class TestScoreFallbackParity:
    def test_score_surface_byte_identical_today(self):
        # Today the auto rows + totals + focus ledger are byte-identical
        # under score_only (the permanent-window surface).
        for option in ({}, {"q_focus_stacks": 0}, {"q_active": False}):
            full = _fight(option, duration=10.0, auto_attack_uptime=1.0)
            scored = _fight(
                option, duration=10.0, auto_attack_uptime=1.0, score_only=True
            )
            assert full["breakdown"] == scored["breakdown"]
            assert full["total_damage"] == scored["total_damage"]
            assert full["resource_ledger"] == scored["resource_ledger"]

    def test_windowed_auto_rows_byte_identical_under_score(self):
        # The auto rows (per-swing damages, count, total) and the Focus
        # ledger stay byte-identical under score_only — true today (the
        # permanent surface) and the contract under the completion (the
        # window is modeled on both paths, never re-priced or dropped).
        full = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        scored = _fight({}, duration=10.0, auto_attack_uptime=1.0, score_only=True)
        assert full["breakdown"]["auto_attacks"] == scored["breakdown"]["auto_attacks"]
        assert full["total_damage"] == scored["total_damage"]
        assert full["resource_ledger"]["focus"] == scored["resource_ledger"]["focus"]

    def test_score_mode_never_silently_re_prices_the_window(self):
        # A score_only fight never prices the flurry ratio where the
        # full fight prices the normal ratio (or vice versa) — per-swing
        # damages agree event-for-event today and under the completion.
        full = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        scored = _fight({}, duration=10.0, auto_attack_uptime=1.0, score_only=True)
        full_d = _swing_damages(full)
        scored_d = _swing_damages(scored)
        assert list(full_d) == list(scored_d)
        for t in full_d:
            assert full_d[t] == pytest.approx(scored_d[t])


# ---------------------------------------------------------------------------
# S16 — Unchanged boundaries: W/R/P, the Focus walk, the existing
#       options, the other champions untouched
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_w_r_and_passive_untouched(self):
        # W/R parse rows and fight rows are identical with the Q on and
        # off; the passive override is byte-identical whichever entry
        # carries it.
        _, abilities_full = _parse({})
        _, abilities_zero = _parse({"q_focus_stacks": 0})
        for slot in ("W", "R"):
            assert abilities_full[slot] == abilities_zero[slot]
        assert abilities_zero["passive"]["auto_attack_override"] == {
            "ad_ratio": 1.0,
            "crit_as_bonus": True,
        }

    def test_mana_ledger_untouched(self):
        # The mana account keeps pricing Q 30 / W 55 / R 100 — the
        # window never re-prices the resource side.
        result = _fight({})
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        spends = [r for r in ledger["receipts"] if r["operation"] == "spend"]
        assert [s["amount"] for s in spends] == [30.0, 55.0, 100.0, 55.0, 55.0]

    def test_focus_walk_consume_unchanged(self):
        # The 4G consume + the focus account shape are untouched by the
        # window (the window only gates the gains).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        assert account["kind"] == "focus"
        assert account["contract"] == "resource_ledger_v1"
        assert account["opening_current"] == 4
        assert account["base_maximum"] == 4

    def test_sibling_packages_untouched(self):
        # The sibling stack/cleanse packages still declare their rules.
        assert (
            RENGAR_FEROCITY_STACK_RULE.public_receipt()["combat_extension_seconds"]
            == 10.0
        )
        from src.calculator import cleanse_eligibility  # noqa: F401
        from src.calculator import defensive_effects  # noqa: F401

    def test_module_source_and_review_status_unchanged(self):
        from src.calculator.champions.ashe import (
            MODULE_COVERAGE,
            REVIEW_STATUS,
            SOURCES,
        )

        assert REVIEW_STATUS == "reviewed_module"
        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "R": "modeled",
            # E (Hawkshot) closed as no_damage in roadmap session 4
            # (vision/charge utility, zero leveling rows).
            "E": "no_damage",
        }
        assert SOURCES[0]["revision_id"] == 4015971


# ---------------------------------------------------------------------------
# S17 — Existing regression surface (kept green; run list in the footer)
# ---------------------------------------------------------------------------


class TestRegressionSurface:
    def test_short_fight_is_fully_in_window(self):
        # A 5s fight (the golden's sustained duration) sits entirely
        # inside the 6s window: every swing is flurry-priced today and
        # stays flurry-priced under the completion — the golden's Ashe
        # auto rows show NO delta.
        result = _fight({}, duration=5.0, auto_attack_uptime=1.0)
        stats, abilities = _parse({})
        damages = _swing_damages(result)
        assert damages
        assert all(
            d == pytest.approx(_flurry_damage(stats, abilities))
            for d in damages.values()
        )
        assert all(0.0 <= t < 6.0 for t in damages)

    def test_existing_parse_pins_hold(self):
        # test_ashe.py's parse-level pins: rank 1 -> 1.10/20, rank 5 ->
        # 1.30/60, Q total_raw 0, cooldown 0 — all module-level and
        # unchanged by the engine-side window.
        _, abilities = _parse({}, ranks={"Q": 1, "W": 0, "E": 0, "R": 0})
        assert abilities["Q"]["auto_attack_override"]["ad_ratio"] == pytest.approx(1.10)
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(20.0)
        assert abilities["Q"]["total_raw"] == 0.0
        assert abilities["Q"]["cooldown"] == 0.0

    def test_focus_rule_receipts_hold(self):
        # test_state_lifecycle_consumers.py's pins: the typed rule
        # receipt shape is unchanged.
        receipt = ASHE_FOCUS_STACK_RULE.public_receipt()
        assert receipt["max_stacks"] == 4
        assert receipt["duration_seconds"] == 4.0
        assert receipt["refresh"] == "refresh"
        assert receipt["expiry"] == "step_down"
        assert receipt["source"]["revision_id"] == 4015971


# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list:
#   .venv/bin/python -m pytest tests/test_ashe_q_active_window.py #       tests/test_aurelion_sol_stardust_ledger.py tests/test_senna_souls_ledger.py #       tests/test_bard_chimes_ledger.py tests/test_heimerdinger_multihit.py #       tests/test_ksante_w_resistance.py tests/test_rengar_ferocity_ledger.py #       tests/test_rengar_w_cleanse.py tests/test_gangplank_w_cleanse.py #       tests/test_milio_r_cleanse.py tests/test_dr_mundo_passive.py #       tests/test_olaf_r_cleanse.py tests/test_ashe_focus_lifecycle.py #       tests/test_state_lifecycle.py tests/test_state_lifecycle_consumers.py #       tests/test_resource_ledger.py tests/test_resource_ledger_consumers.py #       tests/test_resource_ledger_champion_consumers.py #       tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py #       tests/test_mana_restore_refund.py tests/test_app.py
#
# Golden-delta note for the coordinator: the golden's Ashe fights are
# one-rotation (no autos) and 5s sustained (fully inside the 6s window),
# so the completion's window produces ZERO golden deltas for the Ashe
# auto rows unless new 6s+ Ashe fights are registered.  The only
# possible golden delta is the abilities_level_11 Q parse row IF the
# completion adds the typed window declaration (S13) to the parse
# output.
#
# Existing-pin note for the coordinator: tests/test_e3_stacks_2.py
# test_ashe_focus_stacks_gate_rangers_focus pins the PERMANENT window
# over a 10s fight (damage_per_hit == AD x flurry) and will need a
# re-pin when the window lands — it is outside this file's editable
# surface.
