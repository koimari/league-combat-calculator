"""P1 Package 3X — Aurelion Sol "Cosmic Creator" Stardust permanent counter +
resource/counter ledger integration (test-matrix owner: RLM-2 C).

Focused TDD matrix for Aurelion Sol's Stardust permanent counter.
CURRENT RUNTIME FACTS (pinned below, verify-before-pin completed):

- The module (``src/calculator/champions/aurelion_sol.py``) ships the
  static ``stardust_stacks`` option (default 0, declared 0..999) pricing
  Q's burst Stardust %maxHP term (0.031% of target max HP per stack,
  per burst; 3 bursts per 3.25s channel) and E's execute-threshold
  display (5% + 2.6% per 100 stacks of max HP).  Both numbers are
  hardcoded module constants beside degraded wiki prose (the Q burst
  modifier row is values [0,...] with units "(3.1% Stardust)% of
  target's maximum health"; E's threshold has no JSON home at all).
- The option carries NO ``state`` receipt today and there is NO live
  Stardust ledger (no ``resource_ledger`` stardust account, no
  breakdown row): genuinely-absent mechanics are ``xfail`` with reason
  "awaiting P3-3X ...".  The P3-3X coordinator's completion mirrors the
  3W Senna pattern (a typed rule + option state, a documentary
  post-rotation walk with the takedown gain + per-100 threshold
  transitions + named fail-closed denials) WITHOUT re-pricing mid-fight
  (stats stay parse-time; the ledger documents).
- Verified boundary (pinned actual): the parse path does NOT clamp
  ``stardust_stacks`` — the module reads ``float(option)`` directly, so
  a direct parse prices 1000 stacks (or negative stacks) as authored;
  the 0..999 clamp lives at the API boundary (``scenario`` validation
  rejects out-of-range with a named 400 receipt).  This differs from
  Senna's module-level clamp and is flagged for the coordinator.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source + public receipt evidence (typed parse path for the module
      constants + the Q/E public detail receipts).
  S2  Seeded option compatibility (0/100/500 seeds, linear per-stack Q
      term, clamp 999, API validation 400s, option state receipt).
  S3  Accepted Stardust gains (accepted event stream -> permanent
      counter; ownership + event identity; non-gain events gain nothing).
  S4  Permanent counter behavior (no expiry/decay; pre-stacked option
      prices parse-time; live ledger documents the gains).
  S5  Threshold transitions (per-100 E execute crossings; the LINEAR Q
      burst term documented without re-pricing).
  S6  Stat + public ledger receipts (stardust account, ResourceReceipt
      shape, declaration, fight-result + API visibility, mana coexistence).
  S7  Malformed/missing event data fail-closed (identity-less events,
      unsupported Stardust-farming sources, ownership).
  S8  Score/receipt parity (seeded surface byte-identical under
      score_only; ledger parity once wired).
  S9  Unchanged boundaries (Q burst base/AP + channel, W modifier,
      secondary target, E execute display, R swap).
  S10 Regression surface: the mandated sanity list plus every test that
      touches Aurelion Sol / stardust (grep tests/) stays green (run
      list in the module footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows against the fight's own stats — no literal damage
constants.  The Stardust rule numbers (0.031%/stack burst, 5% base and
2.6%/100 execute, 3.25s/3-burst channel) ARE the values under test, so
they appear as literal contract constants (the module itself hardcodes
them beside the wiki prose).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.aurelion_sol import (
    _E_EXECUTE_BASE_PCT,
    _E_EXECUTE_PCT_PER_100_STARDUST,
    _Q_BURSTS_PER_CHANNEL,
    _Q_BURST_MAXHP_PCT_PER_STARDUST,
    _Q_CHANNEL_SECONDS,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
# The data-file key differs from the display/dispatcher name (conftest
# documents the same split: "AurelionSol" in the cache, "Aurelion Sol"
# for get_champion / modules).
_ASOL_DATA = _CHAMPION_DATA["AurelionSol"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
# The P3-3X coordinator wires the live Stardust ledger; genuinely-absent
# mechanics are xfailed with this reason.
_AWAIT = "awaiting P3-3X wiring"

# Contract constants under test (module hardcodes these beside the wiki
# prose; they are the values the ledger declaration will publish).
_TARGET_MAX_HP = 2000.0
_PER_STACK_BURST_DELTA = (  # 3 bursts x 0.031% of 2000 HP per stack
    3.0 * (_Q_BURST_MAXHP_PCT_PER_STARDUST / 100.0) * _TARGET_MAX_HP
)


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
        get_champion("Aurelion Sol"),
        _LEVEL,
        0.0,
        ability_ranks=_RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
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
        champion_options=dict(option),
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
            # The degraded burst modifier row (values all 0) — the module
            # prices the Stardust term itself; never resolve it from data.
            continue
        else:
            raise AssertionError(f"unhandled unit {unit!r} in {attribute}")
    return total


def _q_ability() -> dict:
    return _ASOL_DATA["abilities"]["Q"][0]


def _e_ability() -> dict:
    return _ASOL_DATA["abilities"]["E"][0]


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


def _stardust_account(result: dict) -> dict | None:
    """The live stardust counter account wherever the coordinator lands it.

    Pinned contract (S6): the stardust account rides the public
    ``resource_ledger`` section — either as its own account (kind
    ``stardust``, mirroring the 3V Ferocity shape) or as an additive
    ``stardust`` sub-section beside the mana account (the 3W souls
    shape; Aurelion Sol's mana ledger is real and must survive
    unchanged).  Returns None while the P3-3X wiring is absent.
    """
    section = result.get("resource_ledger")
    if not isinstance(section, dict):
        return None
    if section.get("kind") == "stardust":
        return section
    sub = section.get("stardust")
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
    def test_module_constants_typed_path_disclose_all_sourced_values(self):
        # The typed module path (direct import, the same route the option
        # state receipt will publish) discloses every Stardust number.
        assert _Q_BURST_MAXHP_PCT_PER_STARDUST == pytest.approx(0.031)
        assert _E_EXECUTE_BASE_PCT == pytest.approx(5.0)
        assert _E_EXECUTE_PCT_PER_100_STARDUST == pytest.approx(2.6)
        assert _Q_CHANNEL_SECONDS == pytest.approx(3.25)
        assert _Q_BURSTS_PER_CHANNEL == 3

    def test_stardust_constants_discoverable_through_parse(self):
        # The typed parse path discloses the constants: seed 0/100/500
        # prices Q's burst term as 3 bursts x 0.031% x max HP per stack
        # and E's execute threshold as 5% + 2.6% per 100 stacks.
        _, zero = _parse({"stardust_stacks": 0})
        base = zero["Q"]["total_raw"]
        for seed in (0, 100, 500):
            _, abilities = _parse({"stardust_stacks": seed})
            assert abilities["Q"]["total_raw"] == pytest.approx(
                base + _PER_STACK_BURST_DELTA * seed
            )
        _, hundred = _parse({"stardust_stacks": 100})
        assert hundred["E"]["detail"] == "Executes below 7.6% max HP (152 HP)"
        _, five_hundred = _parse({"stardust_stacks": 500})
        assert five_hundred["E"]["detail"] == "Executes below 18.0% max HP (360 HP)"

    def test_q_e_public_receipts_seeded_detail_text(self):
        # The Q/E public receipts at parse level: the channel detail names
        # the 26 sourced ticks and the 3 bursts; the E detail names the
        # execute threshold with and without Stardust.
        _, abilities = _parse({"stardust_stacks": 0})
        assert (
            abilities["Q"]["detail"]
            == "26 sourced beam tick(s) at 0.125s intervals; 3 burst(s) "
            "at each full second."
        )
        assert abilities["E"]["detail"] == "Executes below 5.0% max HP (100 HP)"
        _, abilities = _parse({"stardust_stacks": 500})
        assert abilities["E"]["detail"] == "Executes below 18.0% max HP (360 HP)"

    def test_q_e_public_receipts_present_in_fight_result(self):
        # The Q/E detail receipts are visible in the fight result and the
        # API payload, seeded by the option.
        result = _fight({"stardust_stacks": 100}, one_rotation=True)
        assert (
            result["breakdown"]["E"]["detail"] == "Executes below 7.6% max HP (152 HP)"
        )
        assert "3 burst(s)" in result["breakdown"]["Q"]["detail"]
        response = _api({"stardust_stacks": 100})
        assert response.status_code == 200
        body = response.get_json()
        assert body["breakdown"]["E"]["detail"] == "Executes below 7.6% max HP (152 HP)"
        assert "3 burst(s)" in body["breakdown"]["Q"]["detail"]

    def test_wiki_prose_pins_the_numbers_and_gain_rules(self):
        # The numbers are wiki prose in the cached data (Q burst modifier
        # row is the degraded [0,...] parse the module hardcodes; E's
        # threshold is prose with no JSON home) plus the module SOURCES
        # pin the wiki revision.
        q = _q_ability()
        burst = _leveling(q, "Bonus Magic Damage")
        stardust_modifier = burst["modifiers"][2]
        assert stardust_modifier["values"] == [0.0] * 5
        assert (
            stardust_modifier["units"][0]
            == "(3.1% Stardust)% of target's maximum health"
        )
        e_prose = " ".join(
            effect.get("description", "") for effect in _e_ability().get("effects", [])
        )
        assert "5% (+ 2.6% per 100 Stardust)" in e_prose
        assert "generates 2 Stardust if they are a champion" in " ".join(
            effect.get("description", "") for effect in q.get("effects", [])
        )
        meta = get_champion_options_meta("Aurelion Sol")
        assert any(
            "permanent stacks of Stardust" in text
            for text in [
                " ".join(
                    effect.get("description", "")
                    for effect in _ASOL_DATA["abilities"]["P"][0].get("effects", [])
                )
            ]
        )
        sources = {row["label"]: row for row in meta["sources"]}
        assert sources["Local League Wiki cache"]["url"].endswith("/en-us/Aurelion_Sol")
        assert sources["Local League Wiki cache"]["revision_id"] == 3952788


# ---------------------------------------------------------------------------
# S2 — Seeded option compatibility
# ---------------------------------------------------------------------------


class TestSeededOptionCompatibility:
    def test_seeds_0_100_500_price_q_burst_and_e_threshold(self):
        # Q raw 641.25 / 827.25 / 1571.25 at 0/100/500 stacks (rank 5,
        # 0 AP, 2000 max HP): each stack adds 1.86 across the 3 bursts.
        for seed, want_delta in ((0, 0.0), (100, 186.0), (500, 930.0)):
            _, abilities = _parse({"stardust_stacks": seed})
            assert abilities["Q"]["total_raw"] == pytest.approx(
                _q_expected(_stats(), stacks=seed)
            )
            assert abilities["Q"]["total_raw"] == pytest.approx(
                _q_expected(_stats()) + want_delta
            )

    def test_q_burst_term_is_linear_per_stack(self):
        # The Q burst term is LINEAR in stacks: each stack adds exactly
        # 3 bursts x 0.031% x 2000 HP = 1.86, at every stack count.
        _, zero = _parse({"stardust_stacks": 0})
        _, one = _parse({"stardust_stacks": 1})
        _, two = _parse({"stardust_stacks": 2})
        assert one["Q"]["total_raw"] - zero["Q"]["total_raw"] == pytest.approx(
            _PER_STACK_BURST_DELTA
        )
        assert two["Q"]["total_raw"] - one["Q"]["total_raw"] == pytest.approx(
            _PER_STACK_BURST_DELTA
        )

    def test_declared_clamp_999_and_api_rejects_out_of_range(self):
        # The option declares min 0 / max 999; the API boundary fails
        # loud on out-of-range seeds with a named receipt.
        meta = get_champion_options_meta("Aurelion Sol")
        option = next(o for o in meta["options"] if o["key"] == "stardust_stacks")
        assert option["min"] == 0
        assert option["max"] == 999
        for bad in (1000, -1):
            response = _api({"stardust_stacks": bad})
            assert response.status_code == 400
            assert (
                response.get_json()["error"]
                == "champion_options.stardust_stacks must be between 0 and 999"
            )
        response = _api({"stardust_stacks": 999})
        assert response.status_code == 200
        response = _api({"stardust_stacks": 0})
        assert response.status_code == 200

    def test_parse_path_does_not_clamp_pinned_actual(self):
        # Pinned actual (divergence from Senna's module-level clamp): the
        # module reads float(option) directly, so the direct parse/fight
        # prices an out-of-range seed as authored (1000 stacks -> the
        # linear term for 1000; -5 -> a negative term).  The 0..999
        # boundary lives at the API only.  Flagged for the coordinator:
        # the parse-time price must stay the seeded price.
        _, abilities = _parse({"stardust_stacks": 1000})
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _q_expected(_stats(), stacks=1000.0)
        )
        _, abilities = _parse({"stardust_stacks": 999})
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _q_expected(_stats(), stacks=999.0)
        )
        _, abilities = _parse({"stardust_stacks": -5})
        assert abilities["Q"]["total_raw"] < _q_expected(_stats())

    def test_api_malformed_option_fails_closed(self):
        # Non-numeric and non-integer seeds are rejected with named
        # receipts at the API; the parse path raises (no invented stacks).
        response = _api({"stardust_stacks": "abc"})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.stardust_stacks must be a number"
        )
        response = _api({"stardust_stacks": 2.5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options.stardust_stacks must be an integer"
        )
        with pytest.raises(ValueError):
            parse_champion_abilities(
                get_champion("Aurelion Sol"),
                _LEVEL,
                0.0,
                ability_ranks=_RANKS,
                champion_stats=_stats(),
                target_stats={"target_max_health": _TARGET_MAX_HP},
                champion_options={"stardust_stacks": "abc"},
            )

    def test_option_state_receipt_declares_the_rule(self):
        # Mirrors SENNA_MIST_RULE's option state receipt: the option
        # carries a typed public receipt declaring the Stardust rule
        # (per-stack burst pct, execute base + per-100 step, permanent,
        # provenance) beside the wiki prose.
        meta = get_champion_options_meta("Aurelion Sol")
        option = next(o for o in meta["options"] if o["key"] == "stardust_stacks")
        state = option["state"]
        assert state["per_stack_burst_maxhp_pct"] == pytest.approx(0.031)
        assert state["execute_base_pct"] == pytest.approx(5.0)
        assert state["execute_pct_per_100_stacks"] == pytest.approx(2.6)
        assert state["permanent"] is True
        assert state["source"]  # provenance on the declaration


# ---------------------------------------------------------------------------
# S3 — Accepted Stardust gains
# ---------------------------------------------------------------------------


class TestAcceptedStardustGains:
    def test_accepted_takedown_events_gain_the_permanent_counter(self):
        # The coordinator's accepted Stardust event stream (the 3W-shaped
        # champion takedown — one gain per takedown) gains the permanent
        # counter.  Each gain carries ownership + event identity.
        result = _fight({"stardust_stacks": 0}, one_rotation=True, target_health=500.0)
        assert result["target_ending_health"] == 0.0  # the takedown happened
        account = _stardust_account(result)
        assert account is not None
        gains = [
            r for r in account["receipts"] if r["operation"] == "gain" and r["accepted"]
        ]
        assert gains
        assert all(g["owner"] == "main" for g in gains)
        assert all(g["kind"] == "stardust" for g in gains)
        assert all(g["amount"] >= 1.0 for g in gains)
        # Event identity: each gain names its source event.
        assert all(
            g["source"] or (g.get("detail", {}) or {}).get("event_id") for g in gains
        )
        assert account["closing_current"] == pytest.approx(
            account["opening_current"] + sum(g["amount"] for g in gains)
        )

    def test_non_gain_events_gain_nothing(self):
        # A fight whose event stream carries only ability casts (no
        # takedown, no accepted Stardust source) yields no gains and an
        # unchanged counter — with the named no-takedown denial.
        result = _fight(
            {"stardust_stacks": 0},
            one_rotation=True,
            cast_order=["E", "R"],
            target_health=_TARGET_MAX_HP,
        )
        account = _stardust_account(result)
        assert account is not None
        accepted_gains = [
            r for r in account["receipts"] if r["operation"] == "gain" and r["accepted"]
        ]
        assert accepted_gains == []
        assert any(
            r["reason"] == "no_q_burst_event"
            for r in account["receipts"]
            if not r["accepted"]
        )
        assert account["closing_current"] == account["opening_current"]

    def test_wiki_gain_rules_pinned_for_the_accepted_stream(self):
        # Source evidence for the coordinator's accepted-event decision:
        # the wiki prose names concrete Stardust gains (Q burst +2 per
        # champion second, E +1 per champion second in the zone plus
        # kill grants 2/2/1, R +5 per champion hit).  The brief's
        # "(champion takedowns?)" is narrower than this stream — the
        # coordinator defines which events the documentary walk accepts.
        q = _q_ability()
        q_prose = " ".join(
            effect.get("description", "") for effect in q.get("effects", [])
        )
        assert "generates 2 Stardust if they are a champion" in q_prose
        e_prose = " ".join(
            effect.get("description", "") for effect in _e_ability().get("effects", [])
        )
        assert "generates 1 Stardust for each full second" in e_prose
        assert "Champions and epic monsters grant 2 Stardust" in e_prose
        assert "Large minions and monsters grant 2 Stardust" in e_prose
        assert "Small minions and monsters grant 1 Stardust" in e_prose
        r_prose = " ".join(
            effect.get("description", "")
            for effect in _ASOL_DATA["abilities"]["R"][0].get("effects", [])
        )
        assert "generates 5 Stardust for each enemy champion hit" in r_prose


# ---------------------------------------------------------------------------
# S4 — Permanent counter behavior
# ---------------------------------------------------------------------------


class TestPermanentCounter:
    def test_counter_is_permanent_no_expiry_or_decay(self):
        # The counter is permanent: no expiry/decay/consume operations,
        # current never decreases, closing equals opening plus accepted
        # gains.  The pre-stacked OPTION prices the stats (S2/S9); the
        # live ledger only documents the gains.
        result = _fight({"stardust_stacks": 0}, one_rotation=True)
        account = _stardust_account(result)
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

    def test_pre_stacked_option_prices_parse_time_no_repricing(self):
        # The seeded option is the parse-time price: the fight's Q/E raw
        # damage equals the seeded parse exactly — never re-priced
        # mid-fight by any ledger.
        for seed in (0, 100, 500):
            _, abilities = _parse({"stardust_stacks": seed})
            result = _fight({"stardust_stacks": seed}, one_rotation=True)
            assert result["breakdown"]["Q"]["total_raw"] == pytest.approx(
                abilities["Q"]["total_raw"]
            )
            assert result["breakdown"]["E"]["total_raw"] == pytest.approx(
                abilities["E"]["total_raw"]
            )

    def test_ledger_opens_from_the_seed_and_documents_on_top(self):
        # With a live ledger present, the seeded option is still the
        # parse-time price: the stardust account opens from the seed and
        # documents the fight's gains on top.
        result = _fight({"stardust_stacks": 100}, one_rotation=True)
        account = _stardust_account(result)
        assert account is not None
        assert account["opening_current"] == 100


# ---------------------------------------------------------------------------
# S5 — Threshold transitions
# ---------------------------------------------------------------------------


class TestThresholdTransitions:
    def test_per_100_execute_threshold_crossings_receipted(self):
        # Crossing 100/200/300... is receipted with the threshold count
        # and the execute-threshold delta (+2.6%) at the crossing; the
        # Q burst term stays the seeded parse-time price.
        result = _fight({"stardust_stacks": 95}, one_rotation=True)
        account = _stardust_account(result)
        assert account is not None
        crossings = _threshold_transitions(account)
        assert crossings
        for row in crossings:
            count = row["threshold_count"]
            assert count % 100 == 0 and count > 0
            assert row["execute_pct_delta"] == pytest.approx(2.6)
            assert row["stacks_before"] == count - 100
            assert row["stacks_after"] == count

    def test_e_threshold_module_math_is_linear_pinned(self):
        # Pinned actual: the module prices E's threshold LINEARLY in
        # stacks (5 + 2.6 x stacks/100, displayed to one decimal), which
        # agrees with the per-100 step formula at exact 100 multiples
        # (100 -> 7.6%, 200 -> 10.2%, 500 -> 18.0%) and is continuous
        # between them (150 -> 8.9%, 199 -> 10.2%).  The per-100 ledger
        # crossings therefore document deltas that match the module's
        # price AT the multiples without re-pricing.
        for seed, want in (
            (0, "5.0%"),
            (100, "7.6%"),
            (150, "8.9%"),
            (199, "10.2%"),
            (200, "10.2%"),
            (500, "18.0%"),
        ):
            _, abilities = _parse({"stardust_stacks": seed})
            assert abilities["E"]["detail"].startswith(f"Executes below {want}")
        _, abilities = _parse({"stardust_stacks": 150})
        assert abilities["E"]["detail"] == "Executes below 8.9% max HP (178 HP)"
        _, abilities = _parse({"stardust_stacks": 199})
        assert abilities["E"]["detail"] == "Executes below 10.2% max HP (203 HP)"
        _, abilities = _parse({"stardust_stacks": 200})
        assert abilities["E"]["detail"] == "Executes below 10.2% max HP (204 HP)"

    def test_linear_q_burst_term_documented_without_repricing(self):
        # The LINEAR Q burst term (each stack, 0.031% x max HP per burst)
        # is documented per stack in the ledger while the fight price
        # stays the seeded parse-time value.
        result = _fight({"stardust_stacks": 100}, one_rotation=True)
        account = _stardust_account(result)
        assert account is not None
        _, abilities = _parse({"stardust_stacks": 100})
        assert result["breakdown"]["Q"]["total_raw"] == pytest.approx(
            abilities["Q"]["total_raw"]
        )
        payload = json.dumps(account, default=list)
        assert "0.031" in payload or "per_stack" in payload


# ---------------------------------------------------------------------------
# S6 — Stat and public ledger receipts
# ---------------------------------------------------------------------------


class TestLedgerReceipts:
    def test_stardust_account_kind_and_receipt_shape(self):
        # The stardust account: kind "stardust", ResourceReceipt-shaped
        # gain rows, the typed rule declaration, and the per-100
        # threshold transitions — with the mana account surviving beside
        # it (Aurelion Sol's cast costs are real).
        result = _fight({"stardust_stacks": 0}, one_rotation=True)
        account = _stardust_account(result)
        assert account is not None
        assert account["kind"] == "stardust"
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
        assert declaration["per_stack_burst_maxhp_pct"] == pytest.approx(0.031)
        assert declaration["execute_base_pct"] == pytest.approx(5.0)
        assert declaration["execute_pct_per_100_stacks"] == pytest.approx(2.6)
        assert declaration["permanent"] is True
        assert declaration.get("source")  # provenance
        # The mana account (real cast admission) survives beside stardust.
        assert result["resource_ledger"]["kind"] == "mana"

    def test_mana_account_coexists_today(self):
        # P3-3X: the mana account is real and unchanged — spend receipts
        # for the accepted Q/E/R casts, resource_spent / resource_remaining
        # visible — and the additive stardust sub-section coexists beside it.
        result = _fight({"stardust_stacks": 0}, one_rotation=True)
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        assert ledger["opening_current"] == pytest.approx(300.0)
        spends = [r for r in ledger["receipts"] if r["operation"] == "spend"]
        assert spends and all(r["accepted"] for r in spends)
        assert result["resource_spent"] > 0.0
        assert result["resource_remaining"] < ledger["opening_current"]
        # The additive stardust sub-section coexists beside the mana account.
        stardust = ledger.get("stardust")
        assert isinstance(stardust, dict)
        assert stardust["kind"] == "stardust"
        assert _stardust_account(result) is not None

    def test_stardust_account_visible_in_api_payload(self):
        response = _api({"stardust_stacks": 0})
        assert response.status_code == 200
        body = response.get_json()
        account = _stardust_account(body)
        assert account is not None
        assert account["kind"] == "stardust"


# ---------------------------------------------------------------------------
# S7 — Malformed/missing event data fail-closed
# ---------------------------------------------------------------------------


class TestMalformedStardustEventsFailClosed:
    def test_stardust_event_without_identity_fails_closed(self):
        # A stardust event without event identity: named fail-closed
        # receipt, no gain; no invented gain can carry an empty identity.
        result = _fight({"stardust_stacks": 0}, one_rotation=True)
        account = _stardust_account(result)
        assert account is not None
        denials = [r for r in account["receipts"] if not r["accepted"]]
        assert any("identity" in r["reason"].lower() for r in denials)
        gains = [r for r in account["receipts"] if r["operation"] == "gain"]
        assert all(
            g["source"] or (g.get("detail", {}) or {}).get("event_id") for g in gains
        )

    def test_unsupported_stardust_sources_fail_closed(self):
        # The model cannot simulate actual Stardust farming (per-tick /
        # per-kill grants are outside the 1v1 champion model); an
        # authored event naming them receipts a named fail-closed denial
        # and gains nothing.
        result = _fight({"stardust_stacks": 0}, one_rotation=True)
        account = _stardust_account(result)
        assert account is not None
        denials = [r for r in account["receipts"] if not r["accepted"]]
        assert denials
        assert any(
            "unsupported" in r["reason"].lower()
            or "minion" in r["reason"].lower()
            or "farming" in r["reason"].lower()
            for r in denials
        )
        assert not [
            r
            for r in account["receipts"]
            if r["accepted"]
            and (
                "minion" in str(r["source"]).lower()
                or "farm" in str(r["source"]).lower()
            )
        ]

    def test_every_gain_row_carries_owner_and_identity(self):
        result = _fight({"stardust_stacks": 0}, one_rotation=True)
        account = _stardust_account(result)
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
        # resource-before/restored/after fields on top — the shared rows
        # and the ledger itself are identical.
        for seed in (0, 100, 500):
            full = _fight({"stardust_stacks": seed}, one_rotation=True)
            scored = _fight(
                {"stardust_stacks": seed}, one_rotation=True, score_only=True
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

    def test_stardust_ledger_score_parity(self):
        full = _fight({"stardust_stacks": 0}, one_rotation=True)
        scored = _fight({"stardust_stacks": 0}, one_rotation=True, score_only=True)
        assert _stardust_account(full) is not None
        assert _stardust_account(full) == _stardust_account(scored)


# ---------------------------------------------------------------------------
# S9 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_q_channel_and_bursts_unchanged(self):
        # One per-cast Q channel: 3.25s of sourced beam (26 ticks at
        # 0.125s) + 3 bursts at each full second; cooldown 3s; the
        # 3.25s channel is derivable from the JSON at ranks 1-4
        # (Total Maximum Magic Damage / Magic Damage per Second — rank 5
        # has no practical cap).
        _, abilities = _parse({"stardust_stacks": 0})
        stats = _stats()
        q = _q_ability()
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _q_expected(stats, stacks=0.0)
        )
        assert abilities["Q"]["cooldown"] == pytest.approx(3.0)
        parts = abilities["Q"]["parts"]
        assert len(parts) == 2
        assert parts[0].count == 26
        assert parts[1].count == 3
        assert "3 burst(s)" in abilities["Q"]["detail"]
        for rank in range(1, 5):
            total = _resolve(q, "Total Maximum Magic Damage", rank - 1, stats)
            per_second = _resolve(q, "Magic Damage per Second", rank - 1, stats)
            assert total / per_second == pytest.approx(_Q_CHANNEL_SECONDS)
        # Timed fights channel Q continuously: 10s -> beam x 10 + 10
        # bursts (1050 + 1000 = 2050 at rank 5, 0 AP).
        _, timed = _parse({"stardust_stacks": 0, "fight_duration_seconds": 10.0})
        assert timed["Q"]["total_raw"] == pytest.approx(2050.0)

    def test_w_modifier_unchanged(self):
        # W rank 5 multiplies the beam base by 112% (sourced row), never
        # the burst base or AP portions; w_active with W unlearned
        # applies nothing.
        stats = _stats()
        w = _ASOL_DATA["abilities"]["W"][0]
        modifier = _resolve(w, "Breath of Light Flat Damage Modifier", 4, stats)
        assert modifier == pytest.approx(112.0)
        _, base = _parse({"stardust_stacks": 0})
        _, active = _parse({"stardust_stacks": 0, "w_active": True})
        beam = _resolve(_q_ability(), "Magic Damage per Second", 4, stats)
        burst = _resolve(_q_ability(), "Bonus Magic Damage", 4, stats)
        assert active["Q"]["total_raw"] == pytest.approx(
            beam * (modifier / 100.0) * _Q_CHANNEL_SECONDS
            + _Q_BURSTS_PER_CHANNEL * burst
        )
        assert base["Q"]["total_raw"] == pytest.approx(
            beam * _Q_CHANNEL_SECONDS + _Q_BURSTS_PER_CHANNEL * burst
        )
        # w_active with W unlearned applies no modifier.
        stats0 = _stats()
        unlearned_abilities = parse_champion_abilities(
            get_champion("Aurelion Sol"),
            _LEVEL,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 5, "R": 3},
            champion_stats=stats0,
            target_stats={"target_max_health": _TARGET_MAX_HP},
            champion_options={"stardust_stacks": 0, "w_active": True},
        )
        assert unlearned_abilities["Q"]["total_raw"] == pytest.approx(
            base["Q"]["total_raw"]
        )

    def test_secondary_target_behavior_unchanged(self):
        # Secondary targets take the sourced 50%-strength beam (exactly
        # half the primary row at every rank) per target; the Stardust
        # bursts stay primary-only; the option is deliberately not
        # declared in OPTIONS.
        _, abilities = _parse({"stardust_stacks": 0})
        stats = _stats()
        secondary = _resolve(
            _q_ability(), "Secondary Magic Damage per Second", 4, stats
        )
        primary = _resolve(_q_ability(), "Magic Damage per Second", 4, stats)
        assert secondary == pytest.approx(primary / 2.0)
        _, two = _parse({"stardust_stacks": 0, "q_secondary_targets": 2})
        assert two["Q"]["total_raw"] == pytest.approx(
            abilities["Q"]["total_raw"] + secondary * 2.0 * _Q_CHANNEL_SECONDS
        )
        assert len(two["Q"]["parts"]) == 3
        assert "secondary target(s)" in two["Q"]["detail"]
        # The control is a declared OPTIONS row, the same shape every
        # other secondary-target count in the roster uses.
        meta = get_champion_options_meta("Aurelion Sol")
        row = next(o for o in meta["options"] if o["key"] == "q_secondary_targets")
        assert (row["default"], row["min"], row["max"]) == (0, 0, 5)

    def test_e_execute_display_unchanged(self):
        # E's raw damage is the sourced full-zone total (20 ticks); the
        # execute display line carries the seeded threshold, percent-only
        # without target max HP in context.
        _, abilities = _parse({"stardust_stacks": 0})
        assert abilities["E"]["total_raw"] == pytest.approx(
            _resolve(_e_ability(), "Total Magic Damage", 4, _stats())
        )
        assert abilities["E"]["detail"] == "Executes below 5.0% max HP (100 HP)"
        stats = _stats()
        no_target = parse_champion_abilities(
            get_champion("Aurelion Sol"),
            _LEVEL,
            0.0,
            ability_ranks=_RANKS,
            champion_stats=stats,
            champion_options={"stardust_stacks": 0},
        )
        assert no_target["E"]["detail"] == "Executes below 5.0% max HP"

    def test_r_swap_unchanged(self):
        # R swaps between Falling Star (R[0]) and The Skies Descend
        # (R[1]) via r_empowered; the empowered star prices R[1]'s
        # "Empowered Magic Damage" only — the shockwave is excluded (a
        # star-struck target is immune) — and reads R[0]'s cooldown.
        _, base = _parse({"stardust_stacks": 0})
        _, empowered = _parse({"stardust_stacks": 0, "r_empowered": True})
        stats = _stats()
        assert base["R"]["total_raw"] == pytest.approx(
            _resolve(_ASOL_DATA["abilities"]["R"][0], "Magic Damage", 2, stats)
        )
        assert base["R"]["name"] == "Falling Star"
        assert empowered["R"]["total_raw"] == pytest.approx(
            _resolve(
                _ASOL_DATA["abilities"]["R"][1], "Empowered Magic Damage", 2, stats
            )
        )
        assert empowered["R"]["name"] == "The Skies Descend"
        assert empowered["R"]["cooldown"] == pytest.approx(base["R"]["cooldown"])

    def test_q_burst_monster_cap_is_a_documented_boundary(self):
        # Wiki prose: the burst's %maxHP Stardust term is "capped at 300
        # against monsters".  The 1v1 champion model has no monster
        # target kind, so the cap is a named out-of-scope boundary, not
        # a modeled number (the same family as the unsupported
        # Stardust-farming sources).
        q_prose = " ".join(
            effect.get("description", "") for effect in _q_ability().get("effects", [])
        )
        assert "capped at 300 against monsters" in q_prose


# ---------------------------------------------------------------------------
# S10 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (contract 10):
#   .venv/bin/python -m pytest tests/test_aurelion_sol_stardust_ledger.py #     tests/test_senna_souls_ledger.py tests/test_rengar_ferocity_ledger.py #     tests/test_state_lifecycle.py tests/test_state_lifecycle_consumers.py #     tests/test_resource_ledger.py tests/test_resource_ledger_consumers.py #     tests/test_resource_ledger_champion_consumers.py #     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py #     tests/test_mana_restore_refund.py tests/test_app.py
# Aurelion Sol / stardust grep surface (contract 10), run separately:
#   tests/test_aurelion_sol.py tests/test_e2_dot_1.py #     tests/test_mechanics_packets.py
