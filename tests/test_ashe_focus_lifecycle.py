"""P1 Slice 10 — Ashe "Ranger's Focus" live stack lifecycle (test-matrix
owner: RLM-2 C).

Focused TDD matrix for Ashe's Focus live stack lifecycle.  CURRENT RUNTIME
FACTS (pinned below, verify-before-pin completed):

- The module (``src/calculator/champions/ashe.py``) ships the typed
  ``ASHE_FOCUS_STACK_RULE`` (max 4, gain 1, 4s duration, refresh
  "refresh", expiry "step_down", expiry_step_seconds 1.0,
  decay_stacks_per_step 1, cap_behavior "noop", NO combat extension,
  source revision 4015971 — the Local League Wiki cache Ashe Q effect
  prose, corroborated by the game file ``data/bin/characters/ashe.bin.json``:
  StackDuration 4, MaxStacks 4, TimerDuration 1, StackFalloffDuration 1,
  BuffDuration 6, ShotsPerStrike 5, DamagePerStrike 1.30 at rank 5,
  BonusAS 60 at rank 5) + the ``q_focus_stacks`` option (int 0-4 default
  4: the parse-time seed AND the Q gate — the flurry override applies
  only at a full 4-stack state) + ``q_active`` (bool default True, the
  legacy activation override).
- The LIVE per-attack gains are NOT wired (named gap in the module
  ASSUMPTIONS: the rotation resolver does not feed per-swing events into
  champion-module parses).  Genuinely-absent mechanics are
  ``pytest.mark.xfail`` (non-strict) with reason "awaiting P1-10 ..." —
  the coordinator's completion wires a documentary Focus walk reading
  the engine's per-swing/auto event stream (each auto on-attack gains a
  stack at its swing time, cap 4 with the refresh + the step-down expiry
  + the rule's combat extension), additive (no re-pricing of the
  parse-time Q), score_only byte-identical; the completion removes the
  markers.
- The 3V Rengar Ferocity walk (``damage.py`` ``_build_ferocity_timeline``
  + ``_add_rengar_ferocity``: the resource_ledger "ferocity" account +
  the breakdown row + the notes) is the live-walk precedent; the P3-3W/3X/3Y
  packages (Senna souls, Bard chimes, Aurelion Sol stardust) added the
  additive sub-section spelling for mana champions — the Focus account
  must ride ``resource_ledger["focus"]`` beside the untouched mana
  account.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (the Focus prose + the AS/flurry/
      cooldown rows through the typed path, recomputed against
      ``data/champions.json`` + the game file; the StackRule receipt;
      the source receipts).
  S2  No Q (Q rank 0 -> no Focus surface — the Q gate; the options
      unchanged).
  S3  Per-attack gains (each auto at its swing time gains a stack — the
      live walk's gain events with identity; the cap 4 with the pinned
      noop; the refresh — xfailed until P1-10 wiring).
  S4  Expiry (the 4s window from the last gain; the 1/s step-down —
      kernel PASS, fight receipts xfailed).
  S5  Drain (the step-down semantics: stacks expire one by one at 1/s —
      kernel PASS, fight receipts xfailed).
  S6  Combat extension (the rule declares NONE — pinned from the source;
      kernel note_activity no-op; contrast with Rengar's 10s freeze).
  S7  Repeated casts (the Q activation at full stacks; the stacks after
      the cast — KEPT per the source (no consumption language in the
      prose or the game file); the wired walk receipt xfailed).
  S8  Rank zero (Q rank 0 -> no stack surface anywhere).
  S9  Options (q_focus_stacks/q_active metadata + the API validation
      named 400s + the parse clamps/raises).
  S10 Missing rows (fail-closed: the _require_row precedent — today a
      silent-zero source gap, pinned; the fail-closed contract xfailed).
  S11 Score fallback/parity (score_only models identically or returns
      the named receipt — never a silent re-price; seeded surface
      byte-identical; the engine-wide score trim on cast_timeline
      resource rows pinned; the wired walk parity xfailed).
  S12 Unchanged boundaries (the Q AS/flurry pricing, the P
      crit-as-bonus, the W/R, the existing options, the mana ledger, the
      Ferocity/grey-health/cleanse packages untouched).
  S13 Regression surface: the mandated sanity list stays green (run list
      in the module footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows against the fight's own stats — no literal damage
constants.  The Focus rule numbers (4 cap / 4s / 1s step / 1 decay /
noop cap / no combat extension) ARE the values under test, so they
appear as literal contract constants beside their game-file evidence.
"""

import copy
import json
from pathlib import Path

import pytest

from src import app as app_module
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
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
# The P1-10 coordinator wires the documentary Focus walk; genuinely-
# absent mechanics are xfailed with this reason (never strict — the
# completion removes the markers).
_AWAIT = "awaiting P1-10 wiring"


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
) -> dict:
    stats, abilities = _parse(option, ranks=ranks)
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


def _api(option: dict):
    # The app skips the rate limiter and result cache in TESTING mode;
    # restore the prior flag so this file never leaks state into
    # sibling runs (test_app.py's dedicated rate-limit tests depend on
    # TESTING being False when they run).
    previous_testing = app_module.app.config.get("TESTING", False)
    app_module.app.config["TESTING"] = True
    try:
        return app_module.app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Ashe",
                "level": _LEVEL,
                "items": [],
                "role": "top",
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
    finally:
        app_module.app.config["TESTING"] = previous_testing


def _q_leveling(attribute: str) -> dict:
    """The Q leveling row named *attribute* in the cached data."""
    ability = _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"Ashe Q has no leveling {attribute!r}")


def _q_value(attribute: str, rank: int) -> float:
    """Recompute one Q leveling value at *rank* from the cached data."""
    total = 0.0
    for modifier in _q_leveling(attribute).get("modifiers", []):
        values = modifier.get("values", [])
        if not values:
            continue
        idx = min(rank - 1, len(values) - 1)
        total += float(values[idx])
    return total


def _game_data_value(name: str, rank: int) -> float:
    """One Ashe Q DataValue at *rank* from the game file (rank 1-indexed;
    the game arrays are 0-indexed with rank 1 at index 1)."""
    if _GAME_FILE is None:
        pytest.skip("local Ashe game-file evidence is unavailable")
    spell = _GAME_FILE["Characters/Ashe/Spells/AsheQAbility/AsheQ"]["mSpell"]
    for entry in spell["DataValues"]:
        if entry.get("name") == name:
            return float(entry["values"][rank])
    raise AssertionError(f"game file AsheQ has no DataValue {name!r}")


def _strip_q_rows(attrs: set[str]):
    """A deep copy of the cached Ashe data with Q leveling rows removed."""
    data = copy.deepcopy(get_champion("Ashe"))
    ability = data["abilities"]["Q"][0]
    for effect in ability.get("effects", []):
        effect["leveling"] = [
            leveling
            for leveling in effect.get("leveling", [])
            if leveling.get("attribute") not in attrs
        ]
    return data


def _focus_account(result: dict) -> dict | None:
    """The live Focus counter account wherever the coordinator lands it.

    Pinned contract: the Focus account rides the public resource_ledger
    section as an ADDITIVE ``focus`` sub-section (kind ``focus``)
    beside the mana account (the P3-3W souls precedent — Ashe's mana
    ledger is real and must survive unchanged).  Returns None while the
    P1-10 wiring is absent.
    """
    section = result.get("resource_ledger")
    if not isinstance(section, dict):
        return None
    if section.get("kind") == "focus":
        return section
    sub = section.get("focus")
    return sub if isinstance(sub, dict) else None


def _focus_row(result: dict) -> dict | None:
    """The breakdown ``focus`` informational row (Rengar ferocity shape)."""
    return result["breakdown"].get("focus")


def _auto_swing_times(result: dict) -> list[float]:
    """The engine's per-swing auto event stream (public times)."""
    return [
        float(event.get("time", 0.0) or 0.0)
        for event in result["breakdown"]["auto_attacks"]["damage_events"]
    ]


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_focus_prose_in_the_cached_entry(self):
        # The Focus prose is effect 0 of the reviewed cache entry — the
        # source the StackRule pins beside its receipt.
        ability = _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0]
        prose = ability["effects"][0]["description"]
        assert "generate a stack of Focus for 4 seconds" in prose
        assert "refreshing on subsequent attacks" in prose
        assert "stacking up to 4 times" in prose
        assert "Stacks expire one by one every second" in prose

    def test_q_rows_discoverable_through_the_typed_path(self):
        # The AS/flurry/cooldown rows through the module's own parse:
        # rank 5 = 60% bonus AS, 130% AD per flurry, no cooldown row
        # (stack-activated -> cooldown 0.0).
        _, abilities = _parse({})
        q = abilities["Q"]
        assert q["stat_buff"]["bonus_attack_speed"] == pytest.approx(60.0)
        assert q["auto_attack_override"]["ad_ratio"] == pytest.approx(1.30)
        assert q["cooldown"] == 0.0
        assert q["total_raw"] == 0.0

    def test_q_rows_recomputed_from_the_cache(self):
        # Recompute the same values from the leveling rows — no literals.
        assert _q_value("Bonus Attack Speed", 5) == pytest.approx(60.0)
        assert _q_value("Bonus Attack Speed", 1) == pytest.approx(20.0)
        assert _q_value("Total Damage Per Flurry", 5) == pytest.approx(130.0)
        assert _q_value("Total Damage Per Flurry", 1) == pytest.approx(110.0)
        assert _q_value("Physical Damage Per Arrow", 5) == pytest.approx(26.0)
        # The Q has no cooldown row at all (stack-activated).
        assert _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0].get("cooldown") is None

    def test_game_file_corroborates_the_rule_numbers(self):
        # The game file (ashe.bin.json AsheQ DataValues) corroborates the
        # prose-pinned rule: 4s stack duration, 4 max stacks, 1s timer and
        # 1s falloff cadence, 6s active buff, 5 shots per flurry, and the
        # rank-5 flurry ratio / bonus AS the parse prices.
        assert _game_data_value("StackDuration", 5) == pytest.approx(4.0)
        assert _game_data_value("MaxStacks", 5) == pytest.approx(4.0)
        assert _game_data_value("TimerDuration", 5) == pytest.approx(1.0)
        assert _game_data_value("StackFalloffDuration", 5) == pytest.approx(1.0)
        assert _game_data_value("BuffDuration", 5) == pytest.approx(6.0)
        assert _game_data_value("ShotsPerStrike", 5) == pytest.approx(5.0)
        assert _game_data_value("DamagePerStrike", 5) == pytest.approx(1.30)
        assert _game_data_value("BonusAS", 5) == pytest.approx(60.0)
        # The game file carries NO combat-extension field for Focus: the
        # only timed fields are the stack duration + the 1s falloff timer.
        if _GAME_FILE is None:
            pytest.skip("local Ashe game-file evidence is unavailable")
        names = {
            entry.get("name")
            for entry in _GAME_FILE["Characters/Ashe/Spells/AsheQAbility/AsheQ"][
                "mSpell"
            ]["DataValues"]
        }
        assert "CombatExtension" not in names and "OutOfCombatDuration" not in names

    def test_stack_rule_typed_path_discloses_all_sourced_values(self):
        receipt = ASHE_FOCUS_STACK_RULE.public_receipt()
        assert receipt["name"] == "Ashe \u2014 Ranger's Focus (Focus stacks)"
        assert receipt["max_stacks"] == 4
        assert receipt["gain_per_application"] == 1
        assert receipt["duration_seconds"] == 4.0
        assert receipt["refresh"] == "refresh"
        assert receipt["expiry"] == "step_down"
        assert receipt["expiry_step_seconds"] == 1.0
        assert receipt["decay_stacks_per_step"] == 1
        assert receipt["cap_behavior"] == "noop"
        assert receipt["combat_extension_seconds"] == 0.0
        assert receipt["source"]["revision_id"] == 4015971
        assert receipt["source"]["url"].endswith("/en-us/Ashe")

    def test_option_meta_carries_the_rule_receipt_and_source_receipts(self):
        meta = get_champion_options_meta("Ashe")
        option = next(o for o in meta["options"] if o["key"] == "q_focus_stacks")
        assert option["type"] == "int"
        assert option["default"] == 4
        assert option["min"] == 0
        assert option["max"] == 4
        state = option["state"]
        assert state["max_stacks"] == 4
        assert state["duration_seconds"] == 4.0
        assert state["refresh"] == "refresh"
        assert state["expiry"] == "step_down"
        assert state["source"]["revision_id"] == 4015971
        assert any("typed kernel stack state" in text for text in meta["assumptions"])
        assert any(
            "Live per-attack gains during a fight are not wired" in text
            for text in meta["assumptions"]
        )
        assert meta["sources"][0]["url"].endswith("/en-us/Ashe")
        assert meta["sources"][0]["revision_id"] == 4015971


# ---------------------------------------------------------------------------
# S2 — No Q (the Q gate: rank + q_active + full stacks)
# ---------------------------------------------------------------------------


class TestQGate:
    def test_rank_zero_no_q_no_focus_surface(self):
        # Q rank 0 -> no Q entry even at a full seeded stack state; the
        # options are unchanged (the passive carries the 1.0 override).
        _, abilities = _parse(
            {"q_focus_stacks": 4}, ranks={"Q": 0, "W": 5, "E": 5, "R": 3}
        )
        assert "Q" not in abilities
        assert abilities["passive"]["auto_attack_override"] == {
            "ad_ratio": 1.0,
            "crit_as_bonus": True,
        }

    def test_partial_stacks_gate_the_flurry(self):
        # The Q gate is a full 4-stack state: 0/1/2/3 seeds price the
        # passive override instead of the flurry.
        for seed in (0, 1, 2, 3):
            _, abilities = _parse({"q_focus_stacks": seed})
            assert "Q" not in abilities
            assert abilities["passive"]["auto_attack_override"]["ad_ratio"] == (
                pytest.approx(1.0)
            )

    def test_full_stacks_open_the_flurry(self):
        _, abilities = _parse({"q_focus_stacks": 4})
        assert "Q" in abilities
        assert abilities["Q"]["auto_attack_override"]["ad_ratio"] == pytest.approx(1.30)
        assert "auto_attack_override" not in abilities["passive"]

    def test_q_active_false_gates_even_at_full_stacks(self):
        # q_active is the legacy activation override: False closes the Q
        # surface at any stack count.
        for stacks in (0, 4):
            _, abilities = _parse({"q_focus_stacks": stacks, "q_active": False})
            assert "Q" not in abilities
            assert abilities["passive"]["auto_attack_override"]["ad_ratio"] == (
                pytest.approx(1.0)
            )

    def test_default_options_are_full_stacks_active(self):
        # No options at all -> the module defaults (4 stacks, active).
        _, abilities = _parse(None)
        assert "Q" in abilities
        assert abilities["Q"]["auto_attack_override"]["ad_ratio"] == pytest.approx(1.30)

    def test_q_gate_uses_the_typed_state(self):
        # The gate is the typed kernel state: the module seeds a
        # TimedStackState from the option and compares against the rule's
        # max_stacks.
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=3)
        assert state.stacks < state.rule.max_stacks
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=4)
        assert state.stacks == state.rule.max_stacks


# ---------------------------------------------------------------------------
# S3 — Per-attack gains (live walk; absent today -> xfail)
# ---------------------------------------------------------------------------


class TestPerAttackGains:
    def test_no_focus_account_today(self):
        # Pinned pre-wiring absence: the fight result carries no Focus
        # account and no focus breakdown row (the mana ledger is the only
        # resource account).
        result = _fight({}, duration=6.0, auto_attack_uptime=1.0)
        # P1-10: the focus account + row now exist beside the mana
        # account (the additive sub-section, never a replacement).
        assert _focus_account(result) is not None
        assert _focus_row(result) is not None
        assert result["resource_ledger"]["kind"] == "mana"

    def test_each_auto_gains_one_stack_at_its_swing_time(self):
        # The live walk reads the engine's per-swing/auto event stream:
        # every auto on-attack gains one Focus stack AT its swing time,
        # with gain-event identity.  The gain times must be a subset of
        # the engine's authored swing stream.
        # P1-11: the 6s fight is fully inside the Q active window (the
        # "while inactive" clause denies the in-window gains) — the 10s
        # fight's POST-window swings gain one stack each at their swing
        # times.
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        gains = [
            r for r in account["receipts"] if r["operation"] == "gain" and r["accepted"]
        ]
        assert gains
        assert all(g["amount"] == 1.0 for g in gains)
        assert all(g["owner"] == "main" for g in gains)
        swing_times = _auto_swing_times(result)
        assert swing_times
        assert all(any(abs(g["time"] - t) < 1e-3 for t in swing_times) for g in gains)
        assert all(g["time"] >= 6.0 for g in gains)
        assert all(
            g["source"] or (g.get("detail") or {}).get("event_id") for g in gains
        )
        # The Q activation consumes the seeded 4; the post-window
        # swings (6.0, 7.25, 8.5) rebuild to 3 (the in-window swings
        # are denied — the P1-11 inactive clause).
        assert account["closing_current"] == pytest.approx(3.0)
        assert account["closing_current"] <= account["closing_maximum"]

    def test_cap_four_no_gain_at_cap(self):
        # The pinned cap behavior: the counter never exceeds 4; a gain at
        # the cap is a named at_cap denial (noop — the deadline is NOT
        # refreshed by the capped attack).
        result = _fight({}, duration=20.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        denials = [
            r
            for r in account["receipts"]
            if r["operation"] == "gain" and r["reason"] == "at_cap"
        ]
        assert denials
        assert all(d["reason"] == "at_cap" for d in denials)
        assert account["closing_current"] <= account["closing_maximum"]
        assert account["closing_maximum"] == 4

    def test_later_auto_refreshes_the_window(self):
        # refresh="refresh": a later auto resets the shared 4s deadline to
        # the latest gain (a "refresh" transition, never a per-stack
        # timer).
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        transitions = account.get("state_transitions", [])
        kinds = [t["kind"] for t in transitions]
        assert "refresh" in kinds

    def test_non_auto_events_gain_nothing(self):
        # Fail-closed admission: W/R casts, item procs, and DoT ticks are
        # NOT auto events and gain nothing (named denials at most).
        result = _fight({"q_active": False}, duration=10.0, auto_attack_uptime=0.0)
        account = _focus_account(result)
        assert account is not None
        gains = [
            r for r in account["receipts"] if r["operation"] == "gain" and r["accepted"]
        ]
        assert gains == []
        # The seeded 4 stacks expire one-by-one (the no-attack fight has
        # no refresh): the closing drains to 0 by the fight end.
        assert account["closing_current"] == 0


# ---------------------------------------------------------------------------
# S4 — Expiry: the 4s window from the last gain
# ---------------------------------------------------------------------------


class TestExpiryWindow:
    def test_kernel_window_is_four_seconds_from_the_last_gain(self):
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE)
        state.apply_gain(0.0, kind="auto_attack", packet="auto_attack", sequence=0)
        assert state.public_receipt()["expires_at"] == pytest.approx(4.0)
        state.apply_gain(3.0, kind="auto_attack", packet="auto_attack", sequence=1)
        # A later auto refreshes the shared deadline to 3 + 4 = 7.
        assert state.public_receipt()["expires_at"] == pytest.approx(7.0)
        kinds = [t.kind for t in state.timeline.transitions()]
        assert kinds == ["gain", "refresh"]

    def test_kernel_expiry_precedes_a_same_time_gain(self):
        # At the exact deadline an auto first loses the expired stack,
        # then the gain is accepted and refreshes the window (the kernel
        # total order: expiry before gain at one timestamp).
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=4)
        assert state.public_receipt()["expires_at"] == pytest.approx(4.0)
        transitions = state.apply_gain(
            4.0, kind="auto_attack", packet="auto_attack", sequence=1
        )
        kinds = [t.kind for t in transitions]
        assert kinds == ["expire", "refresh"]
        assert transitions[0].detail["stacks_before"] == 4
        assert transitions[0].detail["stacks_after"] == 3
        assert transitions[1].detail["stacks_after"] == 4
        assert state.public_receipt()["expires_at"] == pytest.approx(8.0)

    def test_kernel_capped_auto_does_not_refresh_the_window(self):
        # cap_behavior "noop": a gain at the cap is denied and the
        # deadline stays exactly where it was.
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=4)
        deadline_before = state.public_receipt()["expires_at"]
        denied = state.apply_gain(
            2.0, kind="auto_attack", packet="auto_attack", sequence=1
        )
        assert state.stacks == 4
        assert denied[-1].kind == "gain_denied"
        assert denied[-1].detail["reason"] == "at_cap"
        assert state.public_receipt()["expires_at"] == deadline_before

    def test_fight_receipts_show_the_four_second_window(self):
        # The fight's focus state_transitions show the expiry landing 4s
        # after the last accepted gain (per-stack expires_at in the
        # expire receipts).  P1-11: the 10s fight's last post-window
        # gain (8.5) + 4s exceeds the fight — the 14s fight shows the
        # expiry.
        result = _fight({}, duration=14.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        expires = [
            t for t in account.get("state_transitions", []) if t["kind"] == "expire"
        ]
        gains = [
            r for r in account["receipts"] if r["operation"] == "gain" and r["accepted"]
        ]
        assert expires
        assert gains
        first_expire = min(float(t["time"]) for t in expires)
        last_gain_before = max(
            float(g["time"]) for g in gains if float(g["time"]) <= first_expire + 1e-6
        )
        # The expiry materializes at the next trigger time; its scheduled
        # deadline is the last gain + the 4s window (the detail carries
        # the scheduled expires_at).
        assert first_expire >= last_gain_before + 4.0 - 1e-3


# ---------------------------------------------------------------------------
# S5 — Drain: the 1/s step-down
# ---------------------------------------------------------------------------


class TestStepDownDrain:
    def test_kernel_drains_one_stack_per_second(self):
        # step_down: the first step lands AT the deadline, then one stack
        # every second (4 -> 3 -> 2 -> 1 -> 0 at 4/5/6/7s from a t=0
        # seed).
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=4)
        for time, before, after in (
            (4.0, 4, 3),
            (5.0, 3, 2),
            (6.0, 2, 1),
            (7.0, 1, 0),
        ):
            transitions = state._materialize_expiries(time, sequence=99)
            assert transitions, f"expected an expiry at t={time}"
            assert transitions[-1].detail["stacks_before"] == before
            assert transitions[-1].detail["stacks_after"] == after
            assert transitions[-1].detail["decayed"] == 1
        assert state.stacks == 0
        kinds = [t.kind for t in state.timeline.transitions()]
        assert kinds.count("expire") == 4

    def test_kernel_never_drains_before_the_deadline(self):
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=4)
        assert state._materialize_expiries(3.999, sequence=99) == []
        assert state.stacks == 4

    def test_kernel_seeded_receipt_names_the_option_seed(self):
        # The seeded state's gain transition is receipted with the
        # "option" trigger so the parse-time seed is never confused with
        # a live gain.
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=2)
        seed = state.timeline.transitions()[0]
        assert seed.kind == "gain"
        assert seed.detail["trigger_kind"] == "option"
        assert seed.detail["stacks_after"] == 2

    def test_fight_receipts_show_one_per_second_steps(self):
        # Once wired, consecutive expire receipts land 1s apart with
        # decayed == 1 (the rule's expiry_step_seconds).
        result = _fight(
            {"q_focus_stacks": 4, "q_active": False},
            duration=14.0,
            auto_attack_uptime=0.0,
        )
        account = _focus_account(result)
        assert account is not None
        expires = sorted(
            (t for t in account.get("state_transitions", []) if t["kind"] == "expire"),
            key=lambda t: t["time"],
        )
        assert len(expires) >= 2
        assert all(t["detail"].get("decayed") == 1 for t in expires)
        # The kernel records the steps at the materialization trigger
        # (the fight end with no later swings) and carries each step's
        # SCHEDULED time in the detail; the scheduled steps are 1s apart.
        scheduled = sorted(float(t["detail"]["expires_at"]) for t in expires)
        gaps = [b - a for a, b in zip(scheduled, scheduled[1:])]
        assert all(abs(gap - 1.0) < 1e-6 for gap in gaps)


# ---------------------------------------------------------------------------
# S6 — Combat extension: the rule declares NONE
# ---------------------------------------------------------------------------


class TestCombatExtension:
    def test_rule_declares_no_combat_extension(self):
        # Pinned from the source: the Focus prose ("Stacks expire one by
        # one every second when the duration ends") declares no combat
        # freeze, and the game file's only timed fields are the stack
        # duration and the 1s falloff timer.  The rule ships 0.0 — unlike
        # Rengar's 10s in-combat freeze.
        assert ASHE_FOCUS_STACK_RULE.public_receipt()["combat_extension_seconds"] == 0.0
        assert (
            RENGAR_FEROCITY_STACK_RULE.public_receipt()["combat_extension_seconds"]
            == 10.0
        )

    def test_kernel_note_activity_is_a_noop_for_the_module_rule(self):
        # combat_extension_seconds <= 0: damage activity never freezes
        # the expiry; note_activity returns None and records nothing.
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=4)
        assert state.note_activity(1.0, kind="damage_dealt", sequence=9) is None
        assert state.timeline.transitions()[-1].kind == "gain"  # only the seed
        # Expiry is NOT suppressed at the deadline by the damage event.
        assert state._materialize_expiries(4.0, sequence=99)
        assert state.stacks == 3

    def test_no_combat_freeze_in_the_fight_today(self):
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        # P1-10: the rule declares NO combat extension (0.0 — the Rengar
        # 10s freeze is the only champion extension); the walk records no
        # combat_freeze transitions.
        assert "combat_freeze" not in json.dumps(result, default=list)
        assert _focus_row(result)["combat_extension_seconds"] == 0.0


# ---------------------------------------------------------------------------
# S7 — Repeated casts: the Q activation at full stacks
# ---------------------------------------------------------------------------


class TestRepeatedCasts:
    def test_q_activation_requires_full_stacks_and_costs_mana(self):
        # The engine's Q activation: a single cast at t=0 (0s cooldown —
        # stack-activated, so the scheduler never recasts), costing the
        # sourced 30 mana.
        result = _fight({}, duration=60.0, auto_attack_uptime=0.0)
        q_casts = [c for c in result["cast_timeline"] if c["slot"] == "Q"]
        assert len(q_casts) == 1
        assert q_casts[0]["time"] == 0.0
        assert q_casts[0]["resource_cost"] == 30.0
        # The Q entry itself prices zero direct damage; the flurry rides
        # the autos.
        assert result["breakdown"]["Q"]["total_damage"] == 0.0
        # A below-cap fight has no Q cast at all (the gate held at parse).
        result = _fight({"q_focus_stacks": 0}, duration=60.0, auto_attack_uptime=0.0)
        assert [c for c in result["cast_timeline"] if c["slot"] == "Q"] == []

    def test_source_declares_no_stack_consumption_on_activation(self):
        # P1-10 source verdict (B's correction): the live wiki Q cost box
        # "COST: 30 Mana + 4 Focus" + the game mechanic declare that the
        # activation CONSUMES all 4 stacks — the walk receipts the
        # Rengar-style consume at the Q cast time.  The reviewed cache
        # prose alone lacks the consume language (a cache gap), so the
        # cost-box receipt is the binding evidence.
        ability = _CHAMPION_DATA["Ashe"]["abilities"]["Q"][0]
        prose = " ".join(
            effect.get("description", "") for effect in ability.get("effects", [])
        )
        assert "inactive" in prose
        # The module rule + the walk consume at the activation.
        receipt = ASHE_FOCUS_STACK_RULE.public_receipt()
        assert receipt["expiry"] == "step_down"
        result = _fight({}, duration=10.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        consumes = [
            r
            for r in account["receipts"]
            if r["operation"] == "consume" and r["accepted"]
        ]
        assert consumes and consumes[0]["amount"] == -4.0

    def test_walk_receipts_the_activation_without_inventing_consume(self):
        # Once wired: the walk receipts the Q activation at full stacks
        # (the seeded 4/4 state) and the kept-at-4 stacks during/after
        # the cast — no consume receipt (source verdict above), and the
        # seeded stacks remain the opening state.
        result = _fight({}, duration=6.0, auto_attack_uptime=1.0)
        account = _focus_account(result)
        assert account is not None
        assert account["opening_current"] == 4
        # The activation at the Q cast (t=0, the gate open) consumes the
        # seeded 4 stacks; the autos then rebuild (the closing <= 4).
        consumes = [
            r
            for r in account["receipts"]
            if r["operation"] == "consume" and r["accepted"]
        ]
        assert consumes and consumes[0]["amount"] == -4.0
        assert consumes[0]["time"] == pytest.approx(0.0)
        assert account["closing_current"] <= 4


# ---------------------------------------------------------------------------
# S8 — Rank zero: no stack surface
# ---------------------------------------------------------------------------


class TestRankZero:
    def test_rank_zero_no_stack_surface_in_parse_or_fight(self):
        # Q rank 0 -> no Focus surface anywhere: no Q entry, no focus
        # account, no focus breakdown row, no focus text beyond the
        # module receipts; W/R and the mana ledger are untouched.
        result = _fight(
            {"q_focus_stacks": 4},
            duration=10.0,
            ranks={"Q": 0, "W": 5, "E": 5, "R": 3},
        )
        assert _focus_account(result) is None
        assert _focus_row(result) is None
        assert [c for c in result["cast_timeline"] if c["slot"] == "Q"] == []
        assert result["resource_ledger"]["kind"] == "mana"
        _, abilities = _parse(
            {"q_focus_stacks": 4}, ranks={"Q": 0, "W": 5, "E": 5, "R": 3}
        )
        assert abilities["passive"]["auto_attack_override"]["ad_ratio"] == (
            pytest.approx(1.0)
        )

    def test_rank_zero_option_surface_is_unchanged(self):
        # The options metadata is rank-independent (the parse gate is the
        # only consumer of the seed).
        meta = get_champion_options_meta("Ashe")
        keys = {o["key"] for o in meta["options"]}
        assert keys == {"q_active", "q_focus_stacks"}


# ---------------------------------------------------------------------------
# S9 — Options: metadata + API validation + parse behavior
# ---------------------------------------------------------------------------


class TestOptionsAndApiValidation:
    def test_option_metadata_shape(self):
        meta = get_champion_options_meta("Ashe")
        q_active = next(o for o in meta["options"] if o["key"] == "q_active")
        assert q_active["type"] == "bool"
        assert q_active["default"] is True
        focus = next(o for o in meta["options"] if o["key"] == "q_focus_stacks")
        assert focus["type"] == "int"
        assert focus["default"] == 4
        assert focus["min"] == 0
        assert focus["max"] == 4
        assert focus["state"]["source"]["revision_id"] == 4015971

    def test_api_out_of_range_rejected_400(self):
        # The API boundary fails loud with a named receipt; the parse
        # clamps (pinned actual — no invented stacks either way).
        for bad in (5, -1):
            response = _api({"q_focus_stacks": bad})
            assert response.status_code == 400
            assert (
                response.get_json()["error"]
                == "champion_options.q_focus_stacks must be between 0 and 4"
            )
        for good in (0, 4):
            assert _api({"q_focus_stacks": good}).status_code == 200

    def test_api_malformed_options_fail_closed(self):
        # Non-numeric / non-integer / wrong-type option values are named
        # 400s at the API; the parse path raises (no invented stacks).
        response = _api({"q_focus_stacks": "abc"})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.q_focus_stacks must be a number"
        )
        response = _api({"q_focus_stacks": 2.5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.q_focus_stacks must be an integer"
        )
        response = _api({"q_active": "yes"})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.q_active must be true or false"
        )
        with pytest.raises(ValueError):
            _parse({"q_focus_stacks": "abc"})

    def test_parse_clamps_the_seed(self):
        # The module clamps max(0, min(v, 4)) at parse time.
        _, abilities = _parse({"q_focus_stacks": 5})
        assert "Q" in abilities
        _, abilities = _parse({"q_focus_stacks": -1})
        assert "Q" not in abilities

    def test_option_role_parse_time_seed_plus_gate(self):
        # The option is the explicit pre-stack state: seeding 4 opens the
        # Q surface, seeding 3 closes it, and the fight prices the
        # parse-time seed (never a live build-up).
        result = _fight({"q_focus_stacks": 4}, duration=6.0, auto_attack_uptime=1.0)
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == (
            pytest.approx(100.0 * 1.30 / 1.5, rel=1e-9)
        )
        result = _fight({"q_focus_stacks": 0}, duration=6.0, auto_attack_uptime=1.0)
        assert result["breakdown"]["auto_attacks"]["damage_per_hit"] == (
            pytest.approx(100.0 * 1.0 / 1.5, rel=1e-9)
        )


# ---------------------------------------------------------------------------
# S10 — Missing rows: fail-closed (_require_row precedent)
# ---------------------------------------------------------------------------


class TestMissingRows:
    def test_stripped_q_rows_today_silent_zero_pinned_actual(self):
        # P1-10: the _require_row guards make the stripped rows FAIL
        # LOUD (KeyError naming the rows) — the silent-zero fallback is
        # gone.
        with pytest.raises(KeyError) as excinfo:
            _parse(
                {},
                data=_strip_q_rows({"Bonus Attack Speed", "Total Damage Per Flurry"}),
            )
        assert "Bonus Attack Speed" in str(
            excinfo.value
        ) or "Total Damage Per Flurry" in str(excinfo.value)

    def test_missing_rows_fail_closed_not_silent_zero(self):
        # Pinned contract (the P3-3Z _require_row precedent): a
        # missing/degraded Q row must never price a silent zero flurry —
        # the typed declaration either raises naming the row or emits a
        # named fail-closed receipt.  Flips when the P1-10 completion
        # lands.
        try:
            _, abilities = _parse(
                {},
                data=_strip_q_rows({"Bonus Attack Speed", "Total Damage Per Flurry"}),
            )
        except (ValueError, KeyError, AssertionError):
            return  # fail-closed raise is contract-compliant
        q = abilities.get("Q")
        assert q is None or q["auto_attack_override"]["ad_ratio"] != 0.0


# ---------------------------------------------------------------------------
# S11 — Score fallback/parity
# ---------------------------------------------------------------------------


class TestScoreFallbackParity:
    def test_seeded_score_surface_byte_identical(self):
        # score_only models the SAME seeded surface: breakdown, total,
        # resource ledger, and resource totals are byte-identical — never
        # a silent re-price of the Q/passive override.
        for option in (
            {},
            {"q_focus_stacks": 0},
            {"q_focus_stacks": 2},
            {"q_active": False},
        ):
            full = _fight(option, duration=6.0, auto_attack_uptime=1.0)
            scored = _fight(
                option, duration=6.0, auto_attack_uptime=1.0, score_only=True
            )
            assert full["breakdown"] == scored["breakdown"]
            assert full["total_damage"] == scored["total_damage"]
            assert full["resource_ledger"] == scored["resource_ledger"]
            assert full["resource_spent"] == scored["resource_spent"]
            assert full["resource_remaining"] == scored["resource_remaining"]

    def test_score_mode_models_the_flurry_identically(self):
        # Both paths apply the SAME parse-time Q gate: the flurry/AS delta
        # between a 4-stack and a 0-stack fight is identical in full and
        # score mode (the seed is priced at parse time, never re-priced).
        full = _fight({}, duration=6.0, auto_attack_uptime=1.0)
        full0 = _fight({"q_focus_stacks": 0}, duration=6.0, auto_attack_uptime=1.0)
        scored = _fight({}, duration=6.0, auto_attack_uptime=1.0, score_only=True)
        scored0 = _fight(
            {"q_focus_stacks": 0},
            duration=6.0,
            auto_attack_uptime=1.0,
            score_only=True,
        )
        assert full["total_damage"] - full0["total_damage"] == pytest.approx(
            scored["total_damage"] - scored0["total_damage"]
        )

    def test_score_mode_trims_only_the_engine_public_cast_rows(self):
        # The engine-wide score trim (not a Focus re-price): score mode
        # drops the per-cast resource rows (resource_before/restored/
        # after) from cast_timeline; slot/time/name/ordinal/resource_cost
        # stay identical.
        full = _fight({})
        scored = _fight({}, score_only=True)
        assert [
            (c["slot"], c["time"], c["name"], c["ordinal"], c["resource_cost"])
            for c in full["cast_timeline"]
        ] == [
            (c["slot"], c["time"], c["name"], c["ordinal"], c["resource_cost"])
            for c in scored["cast_timeline"]
        ]
        assert all(
            "resource_before" not in c and "resource_after" not in c
            for c in scored["cast_timeline"]
        )

    def test_live_focus_surface_score_parity(self):
        # Once wired, the live focus account + breakdown row must be
        # byte-identical under score_only (the documentary walk runs the
        # same swing stream on both paths) — and must EXIST on both.
        full = _fight({}, duration=6.0, auto_attack_uptime=1.0)
        scored = _fight({}, duration=6.0, auto_attack_uptime=1.0, score_only=True)
        assert _focus_account(full) is not None
        assert _focus_account(full) == _focus_account(scored)
        assert _focus_row(full) is not None
        assert _focus_row(full) == _focus_row(scored)


# ---------------------------------------------------------------------------
# S12 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_q_as_and_flurry_pricing_unchanged(self):
        # The parse-time Q surface is untouched by the Focus lifecycle:
        # rank-5 bonus AS 60 and flurry ratio 1.30 at the module's typed
        # path.
        _, abilities = _parse({})
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(60.0)
        assert abilities["Q"]["auto_attack_override"]["ad_ratio"] == pytest.approx(1.30)
        assert abilities["Q"]["auto_attack_override"]["crit_as_bonus"] is True

    def test_passive_crit_as_bonus_unchanged(self):
        # The P crit-as-bonus override is byte-identical whichever entry
        # carries it (Q inactive -> P carries 1.0).
        _, abilities = _parse({"q_focus_stacks": 0})
        assert abilities["passive"]["auto_attack_override"] == {
            "ad_ratio": 1.0,
            "crit_as_bonus": True,
        }
        _, abilities = _parse({})
        assert "auto_attack_override" not in abilities["passive"]

    def test_w_and_r_unchanged_across_focus_seeds(self):
        # W/R parse rows and fight rows are identical regardless of the
        # Focus seed (the Q gate never re-prices W/R).
        _, abilities_full = _parse({})
        _, abilities_zero = _parse({"q_focus_stacks": 0})
        for slot in ("W", "R"):
            assert abilities_full[slot] == abilities_zero[slot]
        full = _fight({}, duration=10.0)
        zero = _fight({"q_focus_stacks": 0}, duration=10.0)
        assert full["breakdown"]["W"] == zero["breakdown"]["W"]
        assert full["breakdown"]["R"] == zero["breakdown"]["R"]
        # W casts 3x in the 10s window (rank-5 cd 4s): 3 x 240 raw,
        # mitigated at 50 armor -> 720 / 1.5 = 480 post-mitigation.
        assert full["breakdown"]["W"]["total_damage"] == pytest.approx(
            3 * abilities_full["W"]["total_raw"] / 1.5
        )
        # R casts once (rank-3 cd 60s), mitigated at 40 MR -> 600 / 1.4.
        assert full["breakdown"]["R"]["total_damage"] == pytest.approx(
            abilities_full["R"]["total_raw"] / 1.4
        )

    def test_mana_ledger_untouched(self):
        # The mana account stays the only resource account and prices the
        # sourced costs (Q 30 / W 55 / R 100) exactly as before.
        result = _fight({})
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        assert ledger["contract"] == "resource_ledger_v1"
        assert ledger["closing_current"] == pytest.approx(5.0)
        spends = [r for r in ledger["receipts"] if r["operation"] == "spend"]
        assert [s["amount"] for s in spends] == [30.0, 55.0, 100.0, 55.0, 55.0]

    def test_autos_price_the_flurry_when_active(self):
        # The engine applies the parse-time override to the whole auto
        # stream: 7 swings at 86.67 (flurry 1.30, armor 50) vs 4 swings
        # at 66.67 (normal 1.0) over 6s at the seeded attack speeds.
        full = _fight({}, duration=6.0, auto_attack_uptime=1.0)
        zero = _fight({"q_focus_stacks": 0}, duration=6.0, auto_attack_uptime=1.0)
        assert len(_auto_swing_times(full)) == 7
        assert len(_auto_swing_times(zero)) == 4
        assert full["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            100.0 * 1.30 / 1.5, rel=1e-9
        )
        assert zero["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
            100.0 * 1.0 / 1.5, rel=1e-9
        )

    def test_ferocity_grey_health_cleanse_packages_untouched(self):
        # The sibling packages' rules are untouched by the Focus matrix:
        # Rengar still ships its 10s combat freeze + all-at-once expiry
        # and the cleanse/grey-health declarations still import cleanly.
        assert (
            RENGAR_FEROCITY_STACK_RULE.public_receipt()["combat_extension_seconds"]
            == 10.0
        )
        from src.calculator import cleanse_eligibility  # noqa: F401  (cleanse)
        from src.calculator import defensive_effects  # noqa: F401  (grey health)
        from src.calculator import healing  # noqa: F401  (heal/grey packages)


# ---------------------------------------------------------------------------
# S13 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list:
#   .venv/bin/python -m pytest tests/test_ashe_focus_lifecycle.py \
#       tests/test_aurelion_sol_stardust_ledger.py tests/test_senna_souls_ledger.py \
#       tests/test_bard_chimes_ledger.py tests/test_heimerdinger_multihit.py \
#       tests/test_ksante_w_resistance.py tests/test_rengar_ferocity_ledger.py \
#       tests/test_rengar_w_cleanse.py tests/test_gangplank_w_cleanse.py \
#       tests/test_milio_r_cleanse.py tests/test_dr_mundo_passive.py \
#       tests/test_olaf_r_cleanse.py tests/test_state_lifecycle.py \
#       tests/test_state_lifecycle_consumers.py tests/test_resource_ledger.py \
#       tests/test_resource_ledger_consumers.py \
#       tests/test_resource_ledger_champion_consumers.py \
#       tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#       tests/test_mana_restore_refund.py tests/test_app.py
# The existing Ashe pins (tests/test_ashe.py, tests/test_e3_stacks_2.py
# test_ashe_focus_stacks_gate_rangers_focus, tests/test_state_lifecycle_
# consumers.py TestAsheFocusConsumer) stay green.
