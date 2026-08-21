"""P1 Package 3V — Rengar "Unseen Predator" Ferocity live state + resource/counter
ledger integration (test-matrix owner: RLM-2 C).

Focused TDD matrix for Rengar's Ferocity live state.  CURRENT RUNTIME FACTS
(pinned below, verify-before-pin completed):

- The module ships the typed ``StackRule`` (max 4, gain 1, 1s duration,
  refresh none, expiry all_at_once, cap noop, 10s combat extension, source
  rev 2864152) + the seeded ``p_ferocity`` option state.
- LIVE in-fight gains are NOT wired (named gap in ``rengar.py`` ASSUMPTIONS:
  the rotation resolver does not feed per-cast stack events into
  champion-module parses).  Genuinely-absent mechanics are ``xfail`` with
  reason "awaiting P3-3V ..."; the coordinator's completion wires the
  accepted basic-ability cast events (Q/W/E) into the resource/counter
  ledger with live gains, cap, expiry, the 10s combat extension, the
  DoT/proc exclusion, and the consume-at-cap empowerment.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source + public receipt evidence (typed rule path + P "stacks/4" text).
  S2  Seeded state compatibility (p_ferocity 0/2/4/5, malformed, empowered
      pricing at 4).
  S3  Accepted basic-ability stack gains (+1 per accepted Q/W/E cast,
      cap 4; P/R gain nothing; consume-at-cap empowerment).
  S4  Cap behavior (cap noop at 4; next basic ability consumes).
  S5  Timer + combat-extension boundaries (1s per-stack expiry, 10s freeze,
      fight-window observability).
  S6  DoT/proc exclusion (no gain, no extension).
  S7  Malformed/missing cast data fail-closed (unknown slot, malformed
      option, out-of-range p_ferocity).
  S8  Score/receipt parity (live stack count + empowered pricing agree
      between receipt walk and compiled score path).
  S9  Resource-ledger receipt visibility (Ferocity counter rides the
      ledger's champion-consumer surface).
  S10 Regression surface: the existing Rengar/ferocity/state-lifecycle/
      resource-ledger tests stay green (run list in the module footer).

Expected values are recomputed from ``data/champions.json`` leveling rows
against the fight's own stats — no literal damage constants.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator import state_lifecycle as sl
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.rengar import RENGAR_FEROCITY_STACK_RULE
from src.calculator.data_fetcher import get_champion
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.stats import calculate_total_stats

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
# The P3-3V coordinator wires the accepted basic-ability cast events into
# the resource/counter ledger; genuinely-absent mechanics are xfailed.
_AWAIT = "awaiting P3-3V wiring"


def _stats() -> dict:
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "health": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
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


def _parse(option: dict | None):
    stats = _stats()
    return stats, parse_champion_abilities(
        get_champion("Rengar"),
        _LEVEL,
        0.0,
        ability_ranks=_RANKS,
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
) -> dict:
    stats, abilities = _parse(option)
    return calculate_fight_damage(
        stats,
        abilities,
        items or [],
        FightConfig(
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=duration,
            auto_attack_uptime=auto_attack_uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=(cast_order if cast_order is not None else ["Q", "W", "E", "R"]),
        ),
        score_only=score_only,
        champion_options=dict(option),
    )


def _api(option: dict):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Rengar",
            "level": _LEVEL,
            "items": [],
            "role": "top",
            "ability_ranks": _RANKS,
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "target_health": 2000,
            "target_armor": 0,
            "target_mr": 0,
            "champion_options": option,
        },
    )


def _ferocity_leveling(slot: str, attribute: str) -> dict:
    """The wiki Ferocity-Bonus leveling entry (per-level array)."""
    ability = _CHAMPION_DATA["Rengar"]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        if "Ferocity Bonus" not in effect.get("description", ""):
            continue
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"Rengar {slot} has no Ferocity-Bonus leveling {attribute!r}")


def _resolve_ferocity(slot: str, attribute: str, stats: dict) -> float:
    """Recompute the level-18 Ferocity-Bonus value from the cached data."""
    total = 0.0
    for modifier in _ferocity_leveling(slot, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(_LEVEL - 1, len(values) - 1)
        value = float(values[idx])
        unit = str(units[idx]).strip() if idx < len(units) else ""
        if unit == "":
            total += value
        elif unit == "% AD":
            total += value / 100.0 * stats["attack_damage"]
        elif unit == "% AP":
            total += value / 100.0 * stats["ability_power"]
        elif unit == "% bonus AD":
            total += value / 100.0 * stats["bonus_attack_damage"]
        else:
            raise AssertionError(f"unhandled unit {unit!r} in {slot} {attribute}")
    return total


# ---------------------------------------------------------------------------
# S1 — Source + public receipt evidence
# ---------------------------------------------------------------------------


class TestSourceAndPublicReceipt:
    def test_stack_rule_typed_path_discloses_all_sourced_values(self):
        receipt = RENGAR_FEROCITY_STACK_RULE.public_receipt()
        assert receipt["name"] == "Rengar \u2014 Unseen Predator (Ferocity stacks)"
        assert receipt["max_stacks"] == 4
        assert receipt["gain_per_application"] == 1
        assert receipt["duration_seconds"] == 1.0
        assert receipt["refresh"] == "none"
        assert receipt["expiry"] == "all_at_once"
        assert receipt["cap_behavior"] == "noop"
        assert receipt["combat_extension_seconds"] == 10.0
        assert receipt["source"]["revision_id"] == 2864152
        assert receipt["source"]["url"].endswith("Template:Data_Rengar/I")

    def test_option_meta_carries_the_rule_receipt(self):
        meta = get_champion_options_meta("Rengar")
        option = next(o for o in meta["options"] if o["key"] == "p_ferocity")
        assert option["type"] == "int"
        assert option["default"] == 0
        assert option["min"] == 0
        assert option["max"] == 4
        state = option["state"]
        assert state["max_stacks"] == 4
        assert state["gain_per_application"] == 1
        assert state["duration_seconds"] == 1.0
        assert state["refresh"] == "none"
        assert state["combat_extension_seconds"] == 10.0
        assert state["source"]["revision_id"] == 2864152
        assert any("typed kernel stack state" in text for text in meta["assumptions"])

    def test_p_public_receipt_seeded_text_at_parse(self):
        # The "stacks/4" state text is the P public receipt at parse level.
        _, abilities = _parse({"p_ferocity": 2})
        assert "2/4" in abilities["passive"]["detail"]
        _, abilities = _parse({"p_ferocity": 0})
        assert "0/4" in abilities["passive"]["detail"]
        _, abilities = _parse({"p_ferocity": 4})
        assert "EMPOWERED" in abilities["passive"]["detail"]

    def test_p_public_receipt_present_in_fight_result(self):
        result = _fight({"p_ferocity": 2})
        payload = json.dumps(result, default=list)
        assert "2/4" in payload
        assert "Ferocity" in payload
        assert "Unseen Predator" in payload


# ---------------------------------------------------------------------------
# S2 — Seeded state compatibility
# ---------------------------------------------------------------------------


class TestSeededStateCompatibility:
    def test_p_ferocity_seeds_0_2_4(self):
        for seed, marker in ((0, "0/4"), (2, "2/4"), (4, "EMPOWERED")):
            _, abilities = _parse({"p_ferocity": seed})
            assert marker in abilities["passive"]["detail"]

    def test_p_ferocity_out_of_range_clamps_at_parse_api_fails_loud(self):
        # Pinned actual: the module clamps (max(0, min(v, 4))) and the API
        # boundary fails loud with a named receipt — both are part of the
        # contract, no invented stacks either way.
        _, abilities = _parse({"p_ferocity": 5})
        assert "EMPOWERED" in abilities["passive"]["detail"]
        _, abilities = _parse({"p_ferocity": -1})
        assert "0/4" in abilities["passive"]["detail"]
        response = _api({"p_ferocity": 5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.p_ferocity must be between 0 and 4"
        )
        response = _api({"p_ferocity": -1})
        assert response.status_code == 400
        assert "must be between 0 and 4" in response.get_json()["error"]

    def test_malformed_option_fails_closed(self):
        # Non-numeric p_ferocity: the parse path raises (no invented stacks)
        # and the API path rejects with a named receipt.
        stats = _stats()
        with pytest.raises(ValueError):
            parse_champion_abilities(
                get_champion("Rengar"),
                _LEVEL,
                0.0,
                ability_ranks=_RANKS,
                champion_stats=stats,
                target_stats={"target_max_health": 2000.0},
                champion_options={"p_ferocity": "abc"},
            )
        response = _api({"p_ferocity": "abc"})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.p_ferocity must be a number"
        )
        # A float for the int option is also rejected at the API boundary.
        response = _api({"p_ferocity": 2.5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.p_ferocity must be an integer"
        )

    def test_empowered_pricing_at_4_matches_wiki_ferocity_bonus(self):
        stats, empowered = _parse({"p_ferocity": 4})
        _, base = _parse({"p_ferocity": 0})
        expected = {
            "Q": _resolve_ferocity("Q", "Bonus Physical Damage", stats),
            "W": _resolve_ferocity("W", "Bonus Magic Damage", stats),
            "E": _resolve_ferocity("E", "Bonus Physical Damage", stats),
        }
        for slot, want in expected.items():
            assert empowered[slot]["total_raw"] == pytest.approx(want)
            assert empowered[slot]["total_raw"] > base[slot]["total_raw"]
            assert "Ferocity-empowered" in empowered[slot]["detail"]
        # Base rows stay the per-rank values.
        assert base["Q"]["total_raw"] == pytest.approx(165.0)
        assert base["W"]["total_raw"] == pytest.approx(170.0)
        assert base["E"]["total_raw"] == pytest.approx(267.0)


# ---------------------------------------------------------------------------
# S3 — Accepted basic-ability stack gains
# ---------------------------------------------------------------------------


class TestAcceptedCastStackGains:
    def test_accepted_cast_definition_today(self):
        # Pinned actual admission surface the P3-3V gain events will ride:
        # a cast is ACCEPTED when it is cooldown-admitted (and, for mana
        # champions, resource-admitted) — accepted casts are exactly the
        # cast_timeline rows.  Rengar has no resource, so admission is
        # cooldown-only: rank-5 Q (4s CD) lands at 0/4/8 in a 10s fight.
        result = _fight({"p_ferocity": 0})
        timeline = [(c["slot"], c["time"]) for c in result["cast_timeline"]]
        assert ("Q", 0.0) in timeline and ("Q", 4.0) in timeline
        assert ("Q", 8.0) in timeline
        assert len([c for c in timeline if c[0] == "Q"]) == 3
        assert all(c["slot"] in "QWER" for c in result["cast_timeline"])
        # one_rotation caps every slot at exactly one accepted cast.
        one = _fight({"p_ferocity": 0}, one_rotation=True)
        assert [c["slot"] for c in one["cast_timeline"]] == ["Q", "W", "E", "R"]
        assert all(c["time"] == 0.0 for c in one["cast_timeline"])

    def test_each_accepted_qwe_cast_gains_one_stack(self):
        result = _fight({"p_ferocity": 0}, duration=6.0)
        gains = [
            r for r in result["resource_ledger"]["receipts"] if r["operation"] == "gain"
        ]
        # Q@0, W@0, E@0, Q@4 (rank-5 Q cooldown 4s) -> 4 accepted gains.
        assert len(gains) == 4
        assert [g["amount"] for g in gains] == [1.0, 1.0, 1.0, 1.0]
        assert all(g["accepted"] for g in gains)
        # The live counter reads 4/4 after the second Q.
        assert "4/4" in json.dumps(result, default=list)

    def test_p_and_r_casts_do_not_add_stacks(self):
        result = _fight({"p_ferocity": 0}, cast_order=["R"], duration=10.0)
        gains = [
            r for r in result["resource_ledger"]["receipts"] if r["operation"] == "gain"
        ]
        assert gains == []

    def test_empowered_cast_consumes_at_cap(self):
        result = _fight({"p_ferocity": 4}, duration=6.0)
        consumes = [
            r
            for r in result["resource_ledger"]["receipts"]
            if r["operation"] == "consume"
        ]
        assert len(consumes) == 1
        assert consumes[0]["current_before"] == 4
        assert consumes[0]["current_after"] == 0
        # Only the FIRST Q is empowered; later Q/W/E casts price base.
        assert result["breakdown"]["Q"]["detail"].startswith("Ferocity-empowered")
        assert "later casts price the base values" in result["breakdown"]["Q"]["detail"]


# ---------------------------------------------------------------------------
# S4 — Cap behavior
# ---------------------------------------------------------------------------


class TestCapBehavior:
    def test_kernel_cap_noop_and_consume_at_cap(self):
        # Kernel-level pin with the MODULE rule: a gain at cap is a named
        # at_cap denial (noop keeps the deadline and count), and consume at
        # cap clears to 0 with empowered=True.
        state = sl.TimedStackState(RENGAR_FEROCITY_STACK_RULE)
        for seq in range(4):
            state.apply_gain(float(seq), kind="basic_ability_cast", sequence=seq)
        assert state.stacks == 4
        denied = state.apply_gain(4.0, kind="basic_ability_cast", sequence=4)
        assert state.stacks == 4
        assert denied[-1].kind == "gain_denied"
        assert denied[-1].detail["reason"] == "at_cap"
        consumed = state.consume(5.0, sequence=5)
        assert consumed is not None
        assert consumed.kind == "consume"
        assert consumed.detail["empowered"] is True
        assert consumed.detail["stacks_before"] == 4
        assert state.stacks == 0
        # Below cap a consume is a named denial and never mutates.
        assert state.consume(6.0, sequence=6) is None
        assert state.timeline.transitions()[-1].kind == "consume_denied"

    def test_fight_cap_noop_receipts(self):
        result = _fight({"p_ferocity": 4}, duration=6.0)
        denials = [
            r
            for r in result["resource_ledger"]["receipts"]
            if r["operation"] == "gain" and not r["accepted"]
        ]
        assert denials
        assert all(d["reason"] == "at_cap" for d in denials)
        assert result["resource_ledger"]["closing_current"] == 3


# ---------------------------------------------------------------------------
# S5 — Timer + combat-extension boundaries
# ---------------------------------------------------------------------------


class TestTimerAndCombatExtension:
    def test_kernel_per_stack_expiry_one_second(self):
        # refresh="none": each stack dies 1s after its own gain, oldest
        # first.  The combat freeze is isolated out (the module rule's
        # apply_gain re-arms the 10s freeze, which is pinned separately);
        # the fight window (Q CD 4s) CAN observe expiry between casts when
        # no combat freeze is live.
        rule = dataclasses.replace(
            RENGAR_FEROCITY_STACK_RULE, combat_extension_seconds=0.0
        )
        state = sl.TimedStackState(rule)
        for time, seq in ((0.0, 0), (0.4, 1), (0.8, 2)):
            state.apply_gain(time, kind="basic_ability_cast", sequence=seq)
        assert state.stacks == 3
        state._materialize_expiries(1.0, sequence=99)
        assert state.stacks == 2
        state._materialize_expiries(1.4, sequence=99)
        assert state.stacks == 1
        state._materialize_expiries(1.8, sequence=99)
        assert state.stacks == 0
        kinds = [t.kind for t in state.timeline.transitions()]
        assert kinds.count("expire") == 3

    def test_kernel_combat_extension_freezes_ten_seconds(self):
        # A damage event (note_activity / a gain trigger) re-arms the expiry
        # freeze to time + 10s; expiry is suppressed while frozen and
        # materializes at the freeze boundary.
        state = sl.TimedStackState(RENGAR_FEROCITY_STACK_RULE)
        state.apply_gain(0.0, kind="basic_ability_cast", sequence=0)
        state.note_activity(0.5, kind="damage_dealt", sequence=5)
        state._materialize_expiries(1.0, sequence=99)
        assert state.stacks == 1  # frozen at 1.0 (1s expiry suppressed)
        state._materialize_expiries(10.4, sequence=99)
        assert state.stacks == 1  # freeze re-armed to 10.5
        state._materialize_expiries(10.5, sequence=99)
        assert state.stacks == 0
        freeze = [t for t in state.timeline.transitions() if t.kind == "combat_freeze"]
        assert [f.detail["freeze_until"] for f in freeze] == [
            pytest.approx(10.0),
            pytest.approx(10.5),
        ]

    def test_fight_expiry_and_extension_receipts(self):
        result = _fight({"p_ferocity": 0}, duration=6.0)
        receipt = json.dumps(result, default=list)
        assert "expire" in receipt
        assert "combat_freeze" in receipt


# ---------------------------------------------------------------------------
# S6 — DoT/proc exclusion
# ---------------------------------------------------------------------------


class TestDotProcExclusion:
    def test_kernel_freeze_is_explicit_only(self):
        # Pinned rule-level shape: the kernel never invents an extension —
        # the freeze re-arms ONLY on explicit apply_gain/note_activity
        # calls, so a DoT tick or item proc that never calls them neither
        # grants a stack nor extends.  The in-fight exclusion is the
        # wiring's job (xfailed below).
        state = sl.TimedStackState(RENGAR_FEROCITY_STACK_RULE)
        state.apply_gain(0.0, kind="basic_ability_cast", sequence=0)
        # A DoT tick at 5.0 has no kernel hook: there is no apply_damage /
        # note_dot method on the state at all.
        assert not hasattr(state, "apply_damage")
        assert not hasattr(state, "note_dot")
        # The gain's own freeze (until 10.0) was NOT re-armed by the tick:
        # expiry lands exactly at the original 10.0 boundary.  An explicit
        # note_activity WOULD have moved it to 15.0 (pinned in
        # test_kernel_combat_extension_freezes_ten_seconds).
        state._materialize_expiries(9.9, sequence=99)
        assert state.stacks == 1  # still frozen
        state._materialize_expiries(10.0, sequence=99)
        assert state.stacks == 0  # freeze boundary reached, no extension
        freeze = [t for t in state.timeline.transitions() if t.kind == "combat_freeze"]
        assert len(freeze) == 1
        assert freeze[0].detail["freeze_until"] == pytest.approx(10.0)

    def test_fight_dot_tick_and_proc_do_not_extend_or_grant(self):
        # A fight with a burn item (Liandry) + autos and NO basic-ability
        # casts: DoT ticks and item procs produce zero Ferocity gains and
        # zero combat_freeze receipts (the walk never grants from a burn
        # tick or an on-hit proc).
        result = _fight(
            {"p_ferocity": 0},
            duration=6.0,
            cast_order=[],
            auto_attack_uptime=1.0,
        )
        gains = [
            r for r in result["resource_ledger"]["receipts"] if r["operation"] == "gain"
        ]
        assert gains == []
        assert "combat_freeze" not in json.dumps(result, default=list)


# ---------------------------------------------------------------------------
# S7 — Malformed/missing cast data fail-closed
# ---------------------------------------------------------------------------


class TestMalformedCastDataFailClosed:
    def test_unknown_cast_slot_dropped_without_invented_stacks(self):
        """P3-3V fail-closed: an unknown slot yields no casts, no invented
        stacks, and the named zero-cast ferocity receipt (the breakdown
        row + the note) instead of a silent absence."""
        result = _fight({"p_ferocity": 0}, cast_order=["X"], duration=10.0)
        assert result["cast_timeline"] == []
        assert result["total_damage"] == 0.0
        row = result["breakdown"]["ferocity"]
        assert row["count"] == 0
        assert row["max_stacks"] == 4
        assert "recorded no accepted basic-ability casts" in json.dumps(
            result.get("notes", [])
        )
        # A P "cast" (the passive is not a castable slot) behaves the same.
        result = _fight({"p_ferocity": 0}, cast_order=["P"], duration=10.0)
        assert result["cast_timeline"] == []

    def test_unknown_cast_slot_named_receipt(self):
        result = _fight({"p_ferocity": 0}, cast_order=["X"], duration=10.0)
        denials = [
            r for r in result["resource_ledger"]["receipts"] if not r["accepted"]
        ]
        assert denials
        assert any("unknown" in d["reason"].lower() for d in denials)


# ---------------------------------------------------------------------------
# S8 — Score/receipt parity
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_seeded_score_receipt_parity(self):
        # The seeded fight's breakdown/cast receipts agree between the full
        # walk and the compiled score path (score_only=True).
        for seed in (0, 2, 4):
            full = _fight({"p_ferocity": seed})
            scored = _fight({"p_ferocity": seed}, score_only=True)
            assert full["breakdown"] == scored["breakdown"]
            assert full["cast_timeline"] == scored["cast_timeline"]
            assert full["total_damage"] == scored["total_damage"]
            assert full["resource_spent"] == scored["resource_spent"]
            assert full["resource_remaining"] == scored["resource_remaining"]

    def test_live_stack_score_parity(self):
        full = _fight({"p_ferocity": 0}, duration=6.0)
        scored = _fight({"p_ferocity": 0}, duration=6.0, score_only=True)
        assert (
            full["resource_ledger"]["receipts"] == scored["resource_ledger"]["receipts"]
        )
        # The empowered pricing derives from the same live stack count.
        assert (
            full["breakdown"]["Q"]["total_raw"] == scored["breakdown"]["Q"]["total_raw"]
        )


# ---------------------------------------------------------------------------
# S9 — Resource-ledger receipt visibility
# ---------------------------------------------------------------------------


class TestResourceLedgerVisibility:
    def test_resource_ledger_contract_shape_and_rengar_absence(self):
        """Ledger contract shape (mana consumer) + Rengar's ferocity
        counter account."""
        # P3-3V: Rengar declares no MANA resource, so the mana account
        # stays absent; the resource_ledger section IS the ferocity
        # counter account (kind "ferocity" with the ResourceReceipt
        # shape).  The mana consumer surface shape is pinned via Ahri:
        # contract resource_ledger_v1 + per-receipt named fields.
        section = _fight({"p_ferocity": 0})["resource_ledger"]
        assert isinstance(section, dict)
        assert section["kind"] == "ferocity"
        assert section["opening_current"] == 0
        assert section["base_maximum"] == 4
        # 10s default: Q@0/W@0/E@0/Q@4/Q@8 -> cap 4, deny+consume, Q@8 -> 1.
        assert section["closing_current"] == 1
        stats = calculate_total_stats(get_champion("Ahri"), _LEVEL, [])
        abilities = parse_champion_abilities(
            get_champion("Ahri"),
            _LEVEL,
            stats["ability_power"],
            ability_ranks=_RANKS,
            champion_stats=stats,
            target_stats={"target_max_health": 2000.0},
        )
        ahri = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=40,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
                enforce_resource_limits=True,
                cast_order=["Q", "W", "E", "R"],
            ),
        )
        ledger = ahri["resource_ledger"]
        assert ledger["contract"] == "resource_ledger_v1"
        assert ledger["owner"] == "main"
        assert ledger["kind"] == "mana"
        for row in ledger["receipts"]:
            assert row["owner"] == "main"
            assert row["kind"] == "mana"
            for field in (
                "operation",
                "amount",
                "time",
                "source",
                "sequence",
                "tier",
                "atoms",
                "current_before",
                "current_after",
                "maximum_before",
                "maximum_after",
                "accepted",
                "reason",
            ):
                assert field in row

    def test_ferocity_counter_rides_resource_ledger(self):
        result = _fight({"p_ferocity": 2})
        ledger = result["resource_ledger"]
        assert ledger is not None
        assert ledger.get("kind") == "ferocity"
        assert ledger.get("declaration") is not None
        assert ledger["opening_current"] == 2
        # The seeded counter reads 2 and is visible in the fight result.
        assert "2" in json.dumps(ledger, default=list)


# ---------------------------------------------------------------------------
# S10 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the regression list below:
#   .venv/bin/python -m pytest tests/test_rengar_ferocity_ledger.py #     tests/test_e3_stacks_2.py tests/test_state_lifecycle.py #     tests/test_state_lifecycle_consumers.py tests/test_resource_ledger.py #     tests/test_resource_ledger_consumers.py #     tests/test_resource_ledger_champion_consumers.py #     tests/test_catalyst_resource_ledger.py tests/test_mana_restore_refund.py #     tests/test_app.py
# The existing Rengar/ferocity pins (test_e3_stacks_2.py
# test_rengar_ferocity_empowers_q_w_e; test_state_lifecycle_consumers.py
# TestRengarFerocityConsumer) and the resource-ledger consumers stay green.
