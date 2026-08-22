"""P1 Package 3W — Senna "Absolution" Mist soul counter + resource/counter
ledger integration (test-matrix owner: RLM-2 C).

Focused TDD matrix for Senna's Mist soul counter.  CURRENT RUNTIME FACTS
(pinned below, verify-before-pin completed):

- The module (``src/calculator/champions/senna.py``) ships the static
  ``senna_mist_stacks`` option (default 40, clamp 0..300) pricing 0.75
  bonus AD per stack + 20 bonus attack range + 10% crit per 20-stack
  threshold via the parse-time ``stat_buff`` (P Absolution runs first in
  the BUFF phase, so Q/W/R price the Mist-buffed AD).  The values are
  wiki prose (no leveling rows) and the option carries NO ``state``
  receipt today.
- The Weakened Soul mark (P on-hit: level-scaled % CURRENT health on the
  consuming hit, every 2nd hit vs MAX health in the engine convention),
  Relic Cannon (Q's on-hit 20% AD is NOT modeled — named assumption),
  Dawning Shadow (R damage + self-shield flat + 50% AP + 150% Mist for
  3s) and the W root boundaries are unchanged and pinned in S9.
- The 3V package (Rengar) built the ledger-account + post-rotation-walk
  + champion_options-threading infrastructure; Rengar's Ferocity counter
  rides the public ``resource_ledger`` section (kind ``ferocity``).
  Senna's LIVE soul-counter ledger account (kind ``souls``/``mist``) is
  NOT wired: genuinely-absent mechanics are ``xfail`` with reason
  "awaiting P3-3W ..." — the coordinator's completion adds the live
  soul ledger (gains with ownership/event identity, permanent counter,
  every-20 threshold transitions, named fail-closed receipts for
  unsupported events) WITHOUT re-pricing mid-fight (stats stay
  parse-time; the ledger documents).

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source + public receipt evidence (typed parse path for the module
      constants + the P Mist detail receipt).
  S2  Seeded option compatibility (0/40/80 and 0/20/40 seeds, clamp 300,
      API validation 400s, option state receipt).
  S3  Accepted soul gains (accepted soul-event stream -> permanent
      counter; ownership + event identity; non-soul events gain nothing).
  S4  Permanent counter behavior (no expiry, no decay; parse-time
      pricing; live ledger documents gains).
  S5  Every-20 threshold transitions (20/40/60 receipted; range/crit
      deltas at the crossing; no mid-fight re-pricing).
  S6  Stat + public ledger receipts (souls/mist account, ResourceReceipt
      shape, declaration, fight-result + API visibility).
  S7  Malformed/missing event data fail-closed (identity-less events,
      unsupported minion-drop/Wraith-farming sources, ownership).
  S8  Score/receipt parity (seeded surface byte-identical under
      score_only; ledger parity once wired).
  S9  Unchanged boundaries (Weakened Soul mark, Relic Cannon Q, Dawning
      Shadow R shield, W root).
  S10 Regression surface: the mandated sanity list plus every test that
      touches Senna/mist/souls (grep tests/) stays green (run list in
      the module footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows against the fight's own stats — no literal damage
constants.  The Mist rule numbers (0.75 AD/stack, 20/threshold, 20 range,
10% crit) ARE the values under test, so they appear as literal contract
constants (the module itself hardcodes them beside the wiki prose).
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
from src.calculator.data_fetcher import get_champion
from src.calculator.champions.slotlib import find_named_leveling
from tests.parse_stats import parse_stats

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
# The P3-3W coordinator wires the live soul-counter ledger account;
# genuinely-absent mechanics are xfailed with this reason.
_AWAIT = "awaiting P3-3W wiring"


def _parse(option: dict | None):
    stats = parse_stats(_LEVEL)
    return stats, parse_champion_abilities(
        get_champion("Senna"),
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
    target_health: float = 2000.0,
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
            cast_order=(cast_order if cast_order is not None else ["Q", "W", "R"]),
        ),
        score_only=score_only,
        champion_options=dict(option),
    )


def _api(option: dict):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Senna",
            "level": _LEVEL,
            "items": [],
            "role": "support",
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


def _leveling(slot: str, attribute: str) -> dict:
    """The first leveling row named *attribute* in Senna slot *slot*."""
    ability = _CHAMPION_DATA["Senna"]["abilities"][slot][0]
    leveling = find_named_leveling(ability, attribute)
    if leveling is None:
        raise AssertionError(f"Senna {slot} has no leveling {attribute!r}")
    return leveling


def _resolve(slot: str, attribute: str, index: int, stats: dict) -> float:
    """Recompute one slot value from the cached leveling rows.

    Handles the units the Senna packets use: flat, "% bonus AD", "% AP",
    and "% Mist" (skipped — the module adds the 150%-of-Mist term itself
    beside the cached row, pinned in S9).
    """
    total = 0.0
    for modifier in _leveling(slot, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(index, len(values) - 1)
        value = float(values[idx])
        unit = str(units[idx]).strip() if idx < len(units) else ""
        if unit in ("", "seconds"):
            total += value
        elif unit == "% bonus AD":
            total += value / 100.0 * stats["bonus_attack_damage"]
        elif unit == "% AP":
            total += value / 100.0 * stats["ability_power"]
        elif unit == "% Mist":
            continue
        elif unit == "%":
            total += value
        else:
            raise AssertionError(f"unhandled unit {unit!r} in {slot} {attribute}")
    return total


def _souls_account(result: dict) -> dict | None:
    """The live soul-counter account wherever the coordinator lands it.

    Pinned contract (S6): the souls/mist account rides the public
    ``resource_ledger`` section — either as its own account (kind
    ``souls``/``mist``, mirroring the 3V Ferocity shape) or as an
    additive ``souls`` sub-section beside the mana account (Senna's mana
    ledger is real and must survive unchanged).  Returns None while the
    P3-3W wiring is absent.
    """
    section = result.get("resource_ledger")
    if not isinstance(section, dict):
        return None
    if section.get("kind") in ("souls", "mist"):
        return section
    sub = section.get("souls")
    if isinstance(sub, dict):
        return sub
    return None


def _threshold_transitions(account: dict) -> list[dict]:
    """Threshold-crossing rows in either receipted spelling."""
    rows = [r for r in account.get("receipts", []) if r.get("operation") == "threshold"]
    if not rows:
        rows = list(account.get("threshold_transitions", []))
    return rows


# ---------------------------------------------------------------------------
# S1 — Source receipts + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_mist_constants_discoverable_through_parse(self):
        # The typed parse path discloses the module constants: stat_buff
        # carries 0.75 AD/stack and 10% crit per threshold; the range term
        # (20 per threshold) is in the P detail receipt.
        for seed in (20, 40, 80):
            _, abilities = _parse({"senna_mist_stacks": seed})
            buff = abilities["passive"]["stat_buff"]
            thresholds = seed // 20
            assert buff["bonus_attack_damage"] == pytest.approx(0.75 * seed)
            assert buff["critical_strike_chance"] == pytest.approx(10.0 * thresholds)
            assert f"+{20.0 * thresholds:g} range" in abilities["passive"]["detail"]
        # 100 stacks -> 5 thresholds: 75 AD, 50% crit, +100 range.
        _, abilities = _parse({"senna_mist_stacks": 100})
        buff = abilities["passive"]["stat_buff"]
        assert buff["bonus_attack_damage"] == pytest.approx(75.0)
        assert buff["critical_strike_chance"] == pytest.approx(50.0)
        assert "+100 range" in abilities["passive"]["detail"]

    def test_mist_values_in_data_prose_and_sources(self):
        # The numbers are wiki prose in the cached data + module
        # assumptions; the module SOURCES pin the wiki revisions.
        ability = _CHAMPION_DATA["Senna"]["abilities"]["P"][0]
        prose = " ".join(
            effect.get("description", "") for effect in ability.get("effects", [])
        )
        assert "0.75 bonus attack damage" in prose
        assert "every 20 stacks" in prose
        assert "20 bonus attack range" in prose
        assert "10% critical strike chance" in prose
        meta = get_champion_options_meta("Senna")
        assert any(
            "0.75 bonus AD" in text and "20 bonus attack range" in text
            for text in meta["assumptions"]
        )
        assert any(
            "Wraith-farming and mark-consume Mist generation are not simulated" in text
            for text in meta["assumptions"]
        )
        sources = {row["label"]: row for row in meta["sources"]}
        assert sources["Senna parent entry"]["url"].endswith("/en-us/Senna")
        assert sources["Senna parent entry"]["revision_id"] == 4025085
        assert sources["Senna P ability entry"]["url"].endswith("Template:Data_Senna/I")
        assert sources["Senna P ability entry"]["revision_id"] == 2864157

    def test_p_public_receipt_seeded_detail_text(self):
        # The P public receipt: the Mist stat detail at parse level.
        _, abilities = _parse({"senna_mist_stacks": 40})
        assert abilities["passive"]["detail"] == (
            "40 Mist stack(s): +30 bonus AD, +20% crit, +40 range; "
            "mark consume 10% of target max health per 2 hits"
        )
        _, abilities = _parse({"senna_mist_stacks": 0})
        assert "0 Mist stack(s): +0 bonus AD, +0% crit, +0 range" in (
            abilities["passive"]["detail"]
        )

    def test_p_public_receipt_present_in_fight_result(self):
        # The Mist stat receipt is visible in the fight result: the API
        # champion_stats carry the seeded buff, and the R self-shield
        # detail names the selected Mist count.
        response = _api({"senna_mist_stacks": 40})
        assert response.status_code == 200
        body = response.get_json()
        assert body["champion_stats"]["bonus_attack_damage"] == pytest.approx(30.0)
        assert body["champion_stats"]["critical_strike_chance"] == pytest.approx(20.0)
        assert "150% of 40 Mist stacks" in json.dumps(body["breakdown"], default=str)
        result = _fight({"senna_mist_stacks": 40}, one_rotation=True)
        assert (
            result["breakdown"]["on_hit_ability_passive"]["name"]
            == "Weakened Soul (mark consume)"
        )


# ---------------------------------------------------------------------------
# S2 — Seeded option compatibility
# ---------------------------------------------------------------------------


class TestSeededOptionCompatibility:
    def test_seeds_0_40_80_price_the_stats(self):
        # bonus AD 0/30/60 at 0/40/80 (0.75 per stack).
        for seed, want_ad in ((0, 0.0), (40, 30.0), (80, 60.0)):
            _, abilities = _parse({"senna_mist_stacks": seed})
            buff = abilities["passive"]["stat_buff"]
            assert buff["bonus_attack_damage"] == pytest.approx(want_ad)
            assert f"+{want_ad:g} bonus AD" in abilities["passive"]["detail"]

    def test_crit_mapping_both_seed_sets(self):
        # Runtime: 10% crit per 20-stack threshold.  The brief's
        # parenthetical (0/40/80 -> crit 0/10/20) conflates the 0/20/40
        # seed set with 0/40/80; both mappings are pinned exactly:
        # 0/20/40 -> 0/10/20 and 0/40/80 -> 0/20/40.
        for seed, want_crit in ((0, 0.0), (20, 10.0), (40, 20.0)):
            _, abilities = _parse({"senna_mist_stacks": seed})
            assert abilities["passive"]["stat_buff"][
                "critical_strike_chance"
            ] == pytest.approx(want_crit)
        for seed, want_crit in ((0, 0.0), (40, 20.0), (80, 40.0)):
            _, abilities = _parse({"senna_mist_stacks": seed})
            assert abilities["passive"]["stat_buff"][
                "critical_strike_chance"
            ] == pytest.approx(want_crit)
            assert f"+{want_crit:g}% crit" in abilities["passive"]["detail"]

    def test_parse_clamps_300(self):
        # The module clamps the seed to 0..300 (max(0, min(v, 300))).
        _, abilities = _parse({"senna_mist_stacks": 500})
        assert abilities["passive"]["detail"].startswith("300 Mist stack(s)")
        buff = abilities["passive"]["stat_buff"]
        assert buff["bonus_attack_damage"] == pytest.approx(225.0)
        assert buff["critical_strike_chance"] == pytest.approx(150.0)
        assert "+300 range" in abilities["passive"]["detail"]
        _, abilities = _parse({"senna_mist_stacks": -5})
        assert abilities["passive"]["detail"].startswith("0 Mist stack(s)")

    def test_api_out_of_range_rejected_400(self):
        # The API boundary fails loud on out-of-range seeds (the parse
        # clamps, the API does not): named receipts, no invented stacks.
        for bad in (301, -1):
            response = _api({"senna_mist_stacks": bad})
            assert response.status_code == 400
            assert (
                response.get_json()["error"]
                == "champion_options.senna_mist_stacks must be between 0 and 300"
            )
        response = _api({"senna_mist_stacks": 300})
        assert response.status_code == 200
        response = _api({"senna_mist_stacks": 0})
        assert response.status_code == 200

    def test_api_malformed_option_fails_closed(self):
        # Non-numeric and non-integer seeds are rejected with named
        # receipts at the API; the parse path raises (no invented stacks).
        response = _api({"senna_mist_stacks": "abc"})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.senna_mist_stacks must be a number"
        )
        response = _api({"senna_mist_stacks": 2.5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.senna_mist_stacks must be an integer"
        )
        stats = parse_stats(_LEVEL)
        with pytest.raises(ValueError):
            parse_champion_abilities(
                get_champion("Senna"),
                _LEVEL,
                0.0,
                ability_ranks=_RANKS,
                champion_stats=stats,
                target_stats={"target_max_health": 2000.0},
                champion_options={"senna_mist_stacks": "abc"},
            )

    def test_option_state_receipt_declares_the_rule(self):
        # Mirrors p_ferocity's option state receipt: the option carries a
        # typed public receipt declaring the Mist rule (per-stack AD,
        # threshold, range/crit per threshold) with provenance.
        meta = get_champion_options_meta("Senna")
        option = next(o for o in meta["options"] if o["key"] == "senna_mist_stacks")
        state = option["state"]
        assert state["per_stack_bonus_ad"] == pytest.approx(0.75)
        assert state["stacks_per_threshold"] == 20
        assert state["range_per_threshold"] == pytest.approx(20.0)
        assert state["crit_per_threshold"] == pytest.approx(10.0)
        assert state["permanent"] is True
        assert state["source"]  # provenance on the declaration


# ---------------------------------------------------------------------------
# S3 — Accepted soul gains
# ---------------------------------------------------------------------------


class TestAcceptedSoulGains:
    def test_accepted_soul_events_gain_the_permanent_counter(self):
        # The coordinator's accepted soul-event stream (champion
        # takedowns / wraith kills — the wiki prose pins the drop rules:
        # champions and large monsters spawn one wraith, epics two, and
        # killing a wraith grants a stack) gains the permanent counter.
        # Each gain carries ownership + event identity.
        result = _fight({"senna_mist_stacks": 0}, duration=10.0, target_health=500.0)
        account = _souls_account(result)
        assert account is not None
        gains = [
            r for r in account["receipts"] if r["operation"] == "gain" and r["accepted"]
        ]
        assert gains
        assert all(g["owner"] == "main" for g in gains)
        assert all(g["kind"] in ("souls", "mist") for g in gains)
        assert all(g["amount"] >= 1.0 for g in gains)
        # Event identity: each gain names its source event.
        assert all(
            g["source"] or (g.get("detail", {}) or {}).get("event_id") for g in gains
        )
        assert account["closing_current"] == pytest.approx(
            account["opening_current"] + sum(g["amount"] for g in gains)
        )

    def test_non_soul_events_gain_nothing(self):
        # P/R/auto events that are NOT soul sources gain nothing: a fight
        # whose event stream carries only Q/W/R casts and autos yields no
        # soul gains and an unchanged counter.
        result = _fight(
            {"senna_mist_stacks": 0},
            duration=10.0,
            cast_order=["Q", "W", "R"],
            auto_attack_uptime=1.0,
        )
        account = _souls_account(result)
        assert account is not None
        accepted_gains = [
            r for r in account["receipts"] if r["operation"] == "gain" and r["accepted"]
        ]
        assert accepted_gains == []
        assert any(
            r["reason"] == "no_takedown_event"
            for r in account["receipts"]
            if not r["accepted"]
        )
        assert account["closing_current"] == account["opening_current"]


# ---------------------------------------------------------------------------
# S4 — Permanent counter behavior
# ---------------------------------------------------------------------------


class TestPermanentCounter:
    def test_counter_is_permanent_no_expiry_or_decay(self):
        # The counter is permanent: no expiry/decay/consume operations,
        # current never decreases, closing equals opening plus accepted
        # gains.  The pre-stacked OPTION prices the stats (S2/S9); the
        # live ledger only documents the gains.
        result = _fight({"senna_mist_stacks": 0}, duration=10.0)
        account = _souls_account(result)
        assert account is not None
        receipts = account["receipts"]
        assert {r["operation"] for r in receipts} <= {"gain", "clamp"}
        ordered = sorted(receipts, key=lambda r: (float(r["time"]), int(r["sequence"])))
        current = float(account["opening_current"])
        for row in ordered:
            if row["accepted"]:
                assert float(row["current_after"]) >= float(row["current_before"])
                current = float(row["current_after"])
        assert float(account["closing_current"]) == pytest.approx(current)

    def test_pre_stacked_option_prices_stats_ledger_documents(self):
        # The seeded option is the parse-time price even with a live
        # ledger present: seed 40 -> +30 bonus AD / +20% crit / +40 range
        # in the stats, while the souls account starts from the seed and
        # documents the fight's gains on top.
        stats, abilities = _parse({"senna_mist_stacks": 40})
        assert abilities["passive"]["stat_buff"]["bonus_attack_damage"] == (
            pytest.approx(30.0)
        )
        result = _fight({"senna_mist_stacks": 40}, duration=10.0)
        account = _souls_account(result)
        assert account is not None
        assert account["opening_current"] == 40


# ---------------------------------------------------------------------------
# S5 — Every-20 threshold transitions
# ---------------------------------------------------------------------------


class TestThresholdTransitions:
    def test_threshold_crossings_receipted_with_deltas(self):
        # Crossing 20/40/60... is receipted with the threshold count and
        # the range/crit deltas at the crossing (+20 range, +10% crit).
        result = _fight({"senna_mist_stacks": 40}, duration=10.0)
        account = _souls_account(result)
        assert account is not None
        crossings = _threshold_transitions(account)
        assert crossings
        for row in crossings:
            count = row["threshold_count"]
            assert count % 20 == 0 and count > 0
            assert row["range_delta"] == pytest.approx(20.0)
            assert row["crit_delta"] == pytest.approx(10.0)
            assert row["stacks_before"] == count - 20
            assert row["stacks_after"] == count

    def test_no_threshold_transitions_below_20(self):
        result = _fight({"senna_mist_stacks": 0}, duration=5.0)
        account = _souls_account(result)
        assert account is not None
        if float(account["closing_current"]) < 20:
            assert _threshold_transitions(account) == []

    def test_parse_time_price_is_the_fight_price(self):
        # Pinned actual (no live ledger yet): the fight prices the
        # parse-time seed exactly — Q's raw damage is the seed's
        # Mist-buffed value, never re-priced mid-fight.
        result = _fight({"senna_mist_stacks": 40}, one_rotation=True)
        _, abilities = _parse({"senna_mist_stacks": 40})
        q_raw = next(
            e["raw_damage"] for e in result["damage_events"] if e["source_key"] == "Q"
        )
        assert q_raw == pytest.approx(abilities["Q"]["total_raw"])


# ---------------------------------------------------------------------------
# S6 — Stat and public ledger receipts
# ---------------------------------------------------------------------------


class TestLedgerReceipts:
    def test_souls_account_kind_and_receipt_shape(self):
        result = _fight({"senna_mist_stacks": 40})
        account = _souls_account(result)
        assert account is not None
        assert account["kind"] in ("souls", "mist")
        for row in account["receipts"]:
            for field in (
                "owner",
                "kind",
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
        declaration = account["declaration"]
        assert declaration["per_stack_bonus_ad"] == pytest.approx(0.75)
        assert declaration["stacks_per_threshold"] == 20
        assert declaration["range_per_threshold"] == pytest.approx(20.0)
        assert declaration["crit_per_threshold"] == pytest.approx(10.0)
        assert declaration.get("source")  # provenance
        # The mana account (real cast admission) survives beside the
        # souls counter.
        assert result["resource_ledger"]["kind"] == "mana"

    def test_souls_account_visible_in_api_payload(self):
        response = _api({"senna_mist_stacks": 0})
        assert response.status_code == 200
        body = response.get_json()
        account = _souls_account(body)
        assert account is not None
        assert account["kind"] in ("souls", "mist")


# ---------------------------------------------------------------------------
# S7 — Malformed/missing event data fail-closed
# ---------------------------------------------------------------------------


class TestMalformedSoulEventsFailClosed:
    def test_soul_event_without_identity_fails_closed(self):
        # A soul event without event identity (mirrors TearManaflow's
        # missing_hit_identity): named fail-closed receipt, no gain.
        result = _fight({"senna_mist_stacks": 0})
        account = _souls_account(result)
        assert account is not None
        denials = [r for r in account["receipts"] if not r["accepted"]]
        assert any("identity" in r["reason"].lower() for r in denials)
        # No invented gain can carry an empty identity.
        gains = [r for r in account["receipts"] if r["operation"] == "gain"]
        assert all(
            g["source"] or (g.get("detail", {}) or {}).get("event_id") for g in gains
        )

    def test_unsupported_soul_sources_fail_closed(self):
        # Minion-drop simulation and Wraith-farming are NOT simulated
        # (module assumption); an authored event naming them receipts a
        # named fail-closed denial and gains nothing.
        result = _fight({"senna_mist_stacks": 0})
        account = _souls_account(result)
        assert account is not None
        denials = [r for r in account["receipts"] if not r["accepted"]]
        assert denials
        assert any(
            "unsupported" in r["reason"].lower()
            or "wraith" in r["reason"].lower()
            or "minion" in r["reason"].lower()
            for r in denials
        )
        assert not [
            r
            for r in account["receipts"]
            if r["accepted"]
            and (
                "wraith" in str(r["source"]).lower()
                or "minion" in str(r["source"]).lower()
            )
        ]

    def test_every_gain_row_carries_owner_and_identity(self):
        result = _fight({"senna_mist_stacks": 0}, duration=10.0)
        account = _souls_account(result)
        assert account is not None
        gains = [r for r in account["receipts"] if r["operation"] == "gain"]
        assert all(r["owner"] == "main" for r in gains)
        assert all(
            r["source"] or (r.get("detail", {}) or {}).get("event_id") for r in gains
        )


# ---------------------------------------------------------------------------
# S8 — Score/receipt parity
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_seeded_score_receipt_parity(self):
        # The seeded fight's breakdown/cast/receipt surface agrees
        # between the full walk and the compiled score path.  The
        # score-only cast_timeline carries the cast projection
        # (time/slot/name/ordinal/resource_cost); the full walk adds the
        # resource-before/restored/after fields (ledger projections) on
        # top — the shared rows and the ledger itself are identical.
        for seed in (0, 40, 80):
            full = _fight({"senna_mist_stacks": seed}, one_rotation=True)
            scored = _fight(
                {"senna_mist_stacks": seed}, one_rotation=True, score_only=True
            )
            assert full["breakdown"] == scored["breakdown"]
            assert full["total_damage"] == scored["total_damage"]
            assert full["resource_spent"] == scored["resource_spent"]
            assert full["resource_remaining"] == scored["resource_remaining"]
            assert full["resource_ledger"] == scored["resource_ledger"]
            assert len(full["cast_timeline"]) == len(scored["cast_timeline"])
            shared = ("time", "slot", "name", "ordinal", "resource_cost")
            for full_row, scored_row in zip(
                full["cast_timeline"], scored["cast_timeline"]
            ):
                assert {k: full_row[k] for k in shared} == {
                    k: scored_row[k] for k in shared
                }

    def test_souls_ledger_score_parity(self):
        full = _fight({"senna_mist_stacks": 0}, duration=10.0)
        scored = _fight({"senna_mist_stacks": 0}, duration=10.0, score_only=True)
        assert _souls_account(full) is not None
        assert _souls_account(full) == _souls_account(scored)


# ---------------------------------------------------------------------------
# S9 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_weakened_soul_mark_unchanged(self):
        # P mark: level-scaled % CURRENT health on the consuming hit,
        # every 2nd hit (max-health proxy at parse), 4s mark duration.
        _, abilities = _parse({"senna_mist_stacks": 40})
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["name"] == "Weakened Soul (mark consume)"
        assert on_hit["damage_type"] == "physical"
        assert on_hit["stacks_required"] == 2
        assert on_hit["count_ability_hits"] is True
        percent = _resolve("P", "Current Health Damage", _LEVEL - 1, {})
        assert percent == pytest.approx(10.0)  # 1% : 10% by level, level 18
        assert on_hit["damage_per_hit"] == pytest.approx(
            percent / 100.0 * 2000.0 / on_hit["stacks_required"]
        )
        prose = " ".join(
            effect.get("description", "")
            for effect in _CHAMPION_DATA["Senna"]["abilities"]["P"][0].get(
                "effects", []
            )
        )
        assert "4 seconds" in prose and "current health" in prose
        assert any(
            "priced against the target's MAX health" in text
            for text in get_champion_options_meta("Senna")["assumptions"]
        )

    def test_relic_cannon_q_unchanged(self):
        # Q rank 5: 130 : 130 + 60% bonus AD; Mist's 30 AD rides the
        # ratio (70 bonus AD -> 172.0).  Relic Cannon's own on-hit 20% AD
        # stays unmodeled (named assumption).
        _, abilities = _parse({"senna_mist_stacks": 40})
        expected = _resolve(
            "Q",
            "Physical Damage",
            _RANKS["Q"] - 1,
            {"bonus_attack_damage": 70.0, "ability_power": 0.0},
        )
        assert expected == pytest.approx(172.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(expected)
        _, abilities = _parse({"senna_mist_stacks": 0})
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _resolve(
                "Q",
                "Physical Damage",
                _RANKS["Q"] - 1,
                {"bonus_attack_damage": 40.0, "ability_power": 0.0},
            )
        )
        assert any(
            "MODELED as 20% of TOTAL AD" in text
            for text in get_champion_options_meta("Senna")["assumptions"]
        )

    def test_dawning_shadow_r_unchanged(self):
        # R rank 3: 250 : 550 + 115% bonus AD + 70% AP; the self-shield is
        # flat + 50% AP + 150% Mist for 3s (260 at 40 stacks, 0 AP).
        _, abilities = _parse({"senna_mist_stacks": 40})
        expected_damage = _resolve(
            "R",
            "Physical Damage",
            _RANKS["R"] - 1,
            {"bonus_attack_damage": 70.0, "ability_power": 0.0},
        )
        assert expected_damage == pytest.approx(630.5)
        assert abilities["R"]["total_raw"] == pytest.approx(expected_damage)
        flat_ap = _resolve(
            "R",
            "Shield Strength",
            _RANKS["R"] - 1,
            {"bonus_attack_damage": 0.0, "ability_power": 0.0},
        )
        assert flat_ap == pytest.approx(200.0)  # 200 + 50% AP (0)
        (shield,) = abilities["R"]["self_shield_events"]
        assert shield["amount"] == pytest.approx(flat_ap + 1.5 * 40)
        assert shield["amount"] == pytest.approx(260.0)
        assert shield["duration"] == pytest.approx(3.0)
        assert shield["source"] == "Dawning Shadow"
        assert "150% of 40 Mist stacks" in abilities["R"]["detail"]
        # The shield rides the R damage event in the fight result.
        result = _fight({"senna_mist_stacks": 40}, one_rotation=True)
        r_event = next(e for e in result["damage_events"] if e["source_key"] == "R")
        assert r_event["self_shield"]["amount"] == pytest.approx(260.0)
        assert r_event["self_shield"]["duration"] == pytest.approx(3.0)

    def test_w_root_unchanged(self):
        # W rank 5: 230 + 90% bonus AD; the root is the sourced Root
        # Duration row (2.25s at rank 5) riding the damage event.
        _, abilities = _parse({"senna_mist_stacks": 40})
        expected = _resolve(
            "W",
            "Physical Damage",
            _RANKS["W"] - 1,
            {"bonus_attack_damage": 70.0, "ability_power": 0.0},
        )
        assert expected == pytest.approx(293.0)
        assert abilities["W"]["total_raw"] == pytest.approx(expected)
        root = _resolve("W", "Root Duration", _RANKS["W"] - 1, {})
        assert root == pytest.approx(2.25)
        result = _fight({"senna_mist_stacks": 40}, one_rotation=True)
        w_event = next(e for e in result["damage_events"] if e["source_key"] == "W")
        assert w_event["cc_kind"] == "root"
        assert w_event["cc_duration"] == pytest.approx(root)
        assert w_event["cc_reviewed"] is True
        assert w_event["control_source_atoms"]


# ---------------------------------------------------------------------------
# S10 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list, then the Senna/mist/
# souls grep surface (contract 10):
#   .venv/bin/python -m pytest tests/test_senna_souls_ledger.py \
#     tests/test_rengar_ferocity_ledger.py tests/test_mechanics_packets.py \
#     tests/test_state_lifecycle.py tests/test_state_lifecycle_consumers.py \
#     tests/test_resource_ledger.py tests/test_resource_ledger_consumers.py \
#     tests/test_resource_ledger_champion_consumers.py \
#     tests/test_catalyst_resource_ledger.py tests/test_mana_restore_refund.py \
#     tests/test_app.py
# Senna/mist/souls grep surface (contract 10), run separately:
#   tests/test_e3_stacks_3.py tests/test_e8_shields.py \
#     tests/test_cp10_batch_07.py tests/test_e1_healing_b2.py \
#     tests/test_spellblade_on_hit_matrix.py tests/test_champion_primitives.py \
#     tests/test_interaction_atoms.py
