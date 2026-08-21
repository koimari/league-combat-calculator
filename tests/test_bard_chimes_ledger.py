"""P1 Package 3Y — Bard "Traveler's Call" chime counter + meep/resource
ledger integration (test-matrix owner: RLM-2 C).

Focused TDD matrix for Bard's chime counter and meep availability model.
CURRENT RUNTIME FACTS (pinned below, verify-before-pin completed):

- The module (``src/calculator/champions/bard.py``) ships the static
  ``chimes`` option (default 35 — the brief's "3.5 default" is the 35
  chime default, pinned here as 35 — declared 0..200) pricing the meep
  on-hit as 30 (+6 per 5 chimes) (+40% AP) magic damage, hardcoded
  module constants beside the degraded wiki parse (P[0] has no
  leveling rows; the prose survives in the effect descriptions).
- The meep availability model is stock + recharge, two INDEPENDENT
  chime-breakpoint tables checked top-down: stock 1..9 at
  0/10/30/50/65/80/90/95/100 chimes, recharge 8..4s at 0/20/40/55/70
  chimes; ``max_procs`` = stock + floor(fight_duration / recharge) for
  timed fights, stock only for one-rotation/parse.  The fight engine
  empowers the first ``max_procs`` autos (meep on-hit row
  "Traveler's Call (Meep)").
- The meep slow (25%..75% at 5+ chimes) and the 15+ chime splash/cone
  are unmodeled boundaries (module ASSUMPTIONS; single-target model).
- The option carries NO ``state`` receipt today and there is NO live
  chime/meep ledger account (no ``resource_ledger`` sub-section, no
  breakdown row beyond the engine's meep on-hit): genuinely-absent
  mechanics are ``xfail`` with reason "awaiting P3-3Y ...".  The P3-3Y
  coordinator's completion mirrors the 3W Senna / 3X Aurelion Sol
  pattern (a typed chime/meep rule + option state, a documentary
  post-rotation walk with the accepted engine-priced stream, the
  named fail-closed denials) WITHOUT re-pricing mid-fight (stats stay
  parse-time; the ledger documents).
- Verified boundary (pinned actual): the parse path clamps ONLY the
  lower bound (``max(0, int(chimes))``) — 500 chimes price the uncapped
  formula (630 per meep at 0 AP) and a float seed truncates (2.5 == 2);
  the 0..200 clamp lives at the API boundary (named 400 receipts).
  This differs from Senna's module-level 0..300 clamp and matches
  Aurelion Sol's API-only clamp; flagged for the coordinator.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source + public receipt evidence (typed parse path for the module
      constants + the P meep on-hit detail receipt).
  S2  Seeded option compatibility (0/35/100/200 seeds -> meep per-hit +
      stock/recharge, parse clamp pin, API validation 400s, option
      state receipt).
  S3  Accepted live gains (accepted engine-priced stream -> the ledger;
      ownership + event identity; non-events gain nothing).
  S4  Permanent counter/availability (chime counter permanent, meep
      stock + recharge documented, option prices the meep math, ledger
      documents the live events).
  S5  Stat + public ledger receipts (chimes/meeps sub-section,
      ResourceReceipt shape, declaration, availability rows, fight +
      API visibility, mana coexistence).
  S6  Malformed/missing event data fail-closed (chime-collection
      farming, meep-slow, splash events, identity-less events).
  S7  Score/receipt parity (seeded surface byte-identical under
      score_only; ledger parity once wired).
  S8  Unchanged boundaries (meep damage formula, stock/recharge tables,
      max_procs cap, Q, W/E/R exclusions).
  S9  Regression surface: the mandated sanity list plus every test that
      touches Bard / chime / meep (grep tests/) stays green (run list
      in the module footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows against the fight's own stats — no literal damage
constants.  The meep rule numbers (30 base, 6 per 5 chimes, 40% AP,
the stock/recharge breakpoint tables, the 35 default) ARE the values
under test, so they appear as literal contract constants (the module
itself hardcodes them beside the wiki prose).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.bard import (
    _CHIMES_PER_TIER,
    _DEFAULT_CHIMES,
    _MEEP_AP_RATIO,
    _MEEP_BASE,
    _MEEP_PER_TIER,
    _MEEP_RECHARGE_TIERS,
    _MEEP_STOCK_TIERS,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_BARD_DATA = _CHAMPION_DATA["Bard"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P3-3Y coordinator wires the live chime/meep ledger; genuinely-absent
# mechanics are xfailed with this reason.
_AWAIT = "awaiting P3-3Y wiring"


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


def _parse(option: dict | None, *, ap: float = 0.0, ranks: dict | None = None):
    stats = dict(_stats(), ability_power=ap)
    return stats, parse_champion_abilities(
        get_champion("Bard"),
        _LEVEL,
        ap,
        ability_ranks=ranks or _RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option,
    )


def _fight(
    option: dict,
    *,
    duration: float = 10.0,
    uptime: float = 1.0,
    score_only: bool = False,
    one_rotation: bool = False,
    items: list[dict] | None = None,
    target_health: float = _TARGET_MAX_HP,
    cast_order: list[str] | None = None,
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
            auto_attack_uptime=uptime,
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
            "champion": "Bard",
            "level": _LEVEL,
            "items": [],
            "role": "support",
            "ability_ranks": _RANKS,
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "target_health": _TARGET_MAX_HP,
            "target_armor": 50,
            "target_mr": 40,
            "champion_options": option,
        },
    )


def _meep(abilities: dict) -> dict:
    """The P public receipt: the emitted meep on-hit payload."""
    return abilities["passive"]["on_hit"]


def _bard_account(result: dict) -> dict | None:
    """The live chime/meep ledger account wherever the coordinator lands it.

    Pinned contract (S5): the account rides the public
    ``resource_ledger`` section — either as its own account (kind
    ``chimes``/``meeps``, mirroring the 3V Ferocity shape) or as an
    additive sub-section beside the mana account (Bard's mana ledger is
    real and must survive unchanged).  Returns None while the P3-3Y
    wiring is absent.
    """
    section = result.get("resource_ledger")
    if not isinstance(section, dict):
        return None
    if section.get("kind") in ("chimes", "meeps"):
        return section
    for key in ("chimes", "meeps"):
        sub = section.get(key)
        if isinstance(sub, dict):
            return sub
    return None


def _availability(account: dict) -> dict:
    """Meep availability rows in either documented spelling."""
    rows = account.get("availability")
    if isinstance(rows, dict):
        return rows
    declaration = account.get("declaration") or {}
    for key in ("availability", "meep_availability"):
        if isinstance(declaration.get(key), dict):
            return declaration[key]
    return {}


def _leveling(slot: str, attribute: str) -> dict:
    """The first leveling row named *attribute* in one Bard ability entry."""
    ability = _BARD_DATA["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"Bard {slot} has no leveling {attribute!r}")


def _resolve(slot: str, attribute: str, index: int, stats: dict) -> float:
    """Recompute one slot value from the cached leveling rows.

    Handles the units the Bard packets use: flat and "% AP" (Q's
    "Magic Damage" rows are flat values + an 80% AP modifier).
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
        elif unit == "% AP":
            total += value / 100.0 * stats["ability_power"]
        else:
            raise AssertionError(f"unhandled unit {unit!r} in {slot} {attribute}")
    return total


# ---------------------------------------------------------------------------
# S1 — Source receipts + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_module_constants_typed_path_disclose_all_sourced_values(self):
        # The typed module path (direct import, the same route the option
        # state receipt will publish) discloses every meep number: the
        # on-hit formula (30 base, +6 per 5 chimes, 40% AP) and the two
        # independent availability breakpoint tables.
        assert _MEEP_BASE == pytest.approx(30.0)
        assert _MEEP_PER_TIER == pytest.approx(6.0)
        assert _CHIMES_PER_TIER == 5
        assert _MEEP_AP_RATIO == pytest.approx(0.40)
        assert _DEFAULT_CHIMES == 35  # the brief's "3.5 default" is 35
        assert _MEEP_STOCK_TIERS == (
            (100, 9),
            (95, 8),
            (90, 7),
            (80, 6),
            (65, 5),
            (50, 4),
            (30, 3),
            (10, 2),
            (0, 1),
        )
        assert _MEEP_RECHARGE_TIERS == (
            (70, 4.0),
            (55, 5.0),
            (40, 6.0),
            (20, 7.0),
            (0, 8.0),
        )

    def test_meep_formula_discoverable_through_parse(self):
        # The typed parse path prices the formula: 30 + 6 per 5 chimes +
        # 40% AP.  Seeds 0/35/100/200 -> 30/72/150/270 at 0 AP; 35
        # chimes + 100 AP -> 112.
        for seed, want in ((0, 30.0), (35, 72.0), (100, 150.0), (200, 270.0)):
            _, abilities = _parse({"chimes": seed})
            assert _meep(abilities)["damage_per_hit"] == pytest.approx(want)
        _, abilities = _parse({"chimes": 35}, ap=100.0)
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(112.0)

    def test_meep_availability_discoverable_through_parse(self):
        # The typed parse path discloses the availability model: without
        # a fight window max_procs is the stock; with a 10s window it is
        # stock + floor(10 / recharge).  Seeds 0/35/100/200 -> stock
        # 1/3/9/9, recharge 8/7/4/4, max_procs 2/4/11/11.
        for seed, stock, recharge, windowed in (
            (0, 1, 8.0, 2),
            (35, 3, 7.0, 4),
            (100, 9, 4.0, 11),
            (200, 9, 4.0, 11),
        ):
            _, abilities = _parse({"chimes": seed})
            assert _meep(abilities)["max_procs"] == stock
            _, abilities = _parse({"chimes": seed, "fight_duration_seconds": 10.0})
            assert _meep(abilities)["max_procs"] == stock + int(10.0 // recharge)
            assert _meep(abilities)["max_procs"] == windowed

    def test_p_public_receipt_meep_on_hit_detail(self):
        # The P public receipt: the meep on-hit detail at parse level,
        # seeded by the option.
        _, abilities = _parse({"chimes": 35})
        on_hit = _meep(abilities)
        assert on_hit["name"] == "Traveler's Call (Meep)"
        assert on_hit["damage_type"] == "magic"
        assert on_hit["damage_per_hit"] == pytest.approx(72.0)
        assert on_hit["max_procs"] == 3

    def test_p_public_receipt_present_in_fight_result_and_api(self):
        # The meep on-hit receipt is visible in the fight result and the
        # API payload, seeded by the option: 35 chimes over 10s prices
        # max_procs 4 and the 4 first swings carry the meep on-hit.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["name"] == "Traveler's Call (Meep)"
        assert row["count"] == 4
        assert row["damage_per_hit"] == pytest.approx(72.0 * 100 / 140)
        # The API derives the fight window from fight_duration (10s), so
        # the same 35-chime seed prices max_procs 4 there.
        response = _api({"chimes": 35})
        assert response.status_code == 200
        body = response.get_json()
        assert body["breakdown"]["on_hit_ability_passive"]["name"] == (
            "Traveler's Call (Meep)"
        )
        assert body["breakdown"]["on_hit_ability_passive"]["count"] == 4

    def test_wiki_prose_pins_the_numbers_and_boundaries(self):
        # The numbers are wiki prose in the cached data (P[0] has no
        # leveling rows — known-degraded parse) plus the module SOURCES
        # pin the wiki revision.
        p_prose = " ".join(
            effect.get("description", "")
            for effect in _BARD_DATA["abilities"]["P"][0].get("effects", [])
        )
        assert "30 (+ 6 per 5 Chimes collected) (+ 40% AP)" in p_prose
        assert "1 : 9 (based on number of Chimes)" in p_prose
        # The recharge table (8..4s) lives in P's cooldown row units —
        # "50 • 8 : 4 (based on number of Chimes)" — beside the prose.
        p_cooldown_units = " ".join(
            str(unit)
            for modifier in _BARD_DATA["abilities"]["P"][0]
            .get("cooldown", {})
            .get("modifiers", [])
            for unit in modifier.get("units", [])
        )
        assert "8 : 4 (based on number of Chimes)" in p_cooldown_units
        assert "At 5 Chimes, Meeps slow damaged enemies" in p_prose
        assert "At 15 Chimes, Meeps deal the damage to enemies within 150 units" in (
            p_prose
        )
        meta = get_champion_options_meta("Bard")
        assert any("stock + recharge" in text for text in meta["assumptions"])
        assert any(
            "Meep slow and the 15+ chime AoE/cone splash are not modeled" in text
            for text in meta["assumptions"]
        )
        sources = {row["label"]: row for row in meta["sources"]}
        assert sources["Local League Wiki cache"]["url"].endswith("/en-us/Bard")
        assert sources["Local League Wiki cache"]["revision_id"] == 4002472


# ---------------------------------------------------------------------------
# S2 — Seeded option compatibility
# ---------------------------------------------------------------------------


class TestSeededOptionCompatibility:
    def test_seeds_0_35_100_200_price_meep_math(self):
        # per-hit 30/72/150/270 at 0/35/100/200; stock 1/3/9/9 and
        # recharge 8/7/4/4 (10s max_procs 2/4/11/11).
        for seed, per_hit, stock, recharge, windowed in (
            (0, 30.0, 1, 8.0, 2),
            (35, 72.0, 3, 7.0, 4),
            (100, 150.0, 9, 4.0, 11),
            (200, 270.0, 9, 4.0, 11),
        ):
            _, abilities = _parse({"chimes": seed})
            assert _meep(abilities)["damage_per_hit"] == pytest.approx(per_hit)
            assert _meep(abilities)["max_procs"] == stock
            _, abilities = _parse({"chimes": seed, "fight_duration_seconds": 10.0})
            assert _meep(abilities)["max_procs"] == windowed
            assert stock == next(
                v for threshold, v in _MEEP_STOCK_TIERS if seed >= threshold
            )
            assert recharge == next(
                v for threshold, v in _MEEP_RECHARGE_TIERS if seed >= threshold
            )

    def test_parse_clamp_lower_zero_no_upper_pinned_actual(self):
        # Pinned actual (divergence from Senna's module-level clamp): the
        # module reads max(0, int(chimes)) — negative seeds clamp to 0,
        # but there is NO upper clamp, so the direct parse prices 500
        # chimes as authored (630 per meep).  The 0..200 boundary lives
        # at the API only.  Flagged for the coordinator: the parse-time
        # price must stay the seeded price.
        _, abilities = _parse({"chimes": -5})
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(30.0)
        assert _meep(abilities)["max_procs"] == 1
        _, abilities = _parse({"chimes": 500})
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(630.0)
        _, abilities = _parse({"chimes": 200})
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(270.0)

    def test_parse_truncates_float_seed_pinned_actual(self):
        # Pinned actual: the parse path int()s the seed, so 2.5 prices
        # exactly like 2 (30 per meep, stock 1); the API boundary rejects
        # non-integers with a named 400 receipt (below).
        _, truncated = _parse({"chimes": 2.5})
        _, integer = _parse({"chimes": 2})
        assert _meep(truncated) == _meep(integer)
        assert _meep(truncated)["damage_per_hit"] == pytest.approx(30.0)

    def test_declared_clamp_200_and_api_rejects_out_of_range(self):
        # The option declares min 0 / max 200; the API boundary fails
        # loud on out-of-range seeds with a named receipt.
        meta = get_champion_options_meta("Bard")
        option = next(o for o in meta["options"] if o["key"] == "chimes")
        assert option["min"] == 0
        assert option["max"] == 200
        assert option["default"] == 35
        for bad in (201, -1):
            response = _api({"chimes": bad})
            assert response.status_code == 400
            assert (
                response.get_json()["error"]
                == "champion_options.chimes must be between 0 and 200"
            )
        response = _api({"chimes": 200})
        assert response.status_code == 200
        response = _api({"chimes": 0})
        assert response.status_code == 200

    def test_api_malformed_option_fails_closed(self):
        # Non-numeric and non-integer seeds are rejected with named
        # receipts at the API; the parse path raises on non-numeric
        # (no invented chimes).
        response = _api({"chimes": "abc"})
        assert response.status_code == 400
        assert (
            response.get_json()["error"] == "champion_options.chimes must be a number"
        )
        response = _api({"chimes": 2.5})
        assert response.status_code == 400
        assert (
            response.get_json()["error"] == "champion_options.chimes must be an integer"
        )
        stats = _stats()
        with pytest.raises(ValueError):
            parse_champion_abilities(
                get_champion("Bard"),
                _LEVEL,
                0.0,
                ability_ranks=_RANKS,
                champion_stats=stats,
                target_stats={"target_max_health": _TARGET_MAX_HP},
                champion_options={"chimes": "abc"},
            )

    def test_option_state_receipt_declares_the_rule(self):
        # Mirrors SENNA_MIST_RULE's option state receipt: the option
        # carries a typed public receipt declaring the chime/meep rule
        # (meep base, per-tier, chimes per tier, AP ratio, the
        # availability breakpoint tables, permanent, provenance).
        meta = get_champion_options_meta("Bard")
        option = next(o for o in meta["options"] if o["key"] == "chimes")
        state = option["state"]
        assert state["meep_base"] == pytest.approx(30.0)
        assert state["meep_per_tier"] == pytest.approx(6.0)
        assert state["chimes_per_tier"] == 5
        assert state["meep_ap_ratio"] == pytest.approx(0.40)
        assert state["permanent"] is True
        assert state["source"]  # provenance on the declaration


# ---------------------------------------------------------------------------
# S3 — Accepted live gains
# ---------------------------------------------------------------------------


class TestAcceptedLiveGains:
    def test_accepted_meep_consumption_events_receipted(self):
        # The accepted engine-priced stream is MEEP CONSUMPTION: the
        # engine prices max_procs (stock + floor(duration / recharge))
        # empowered autos, and each empowered auto consumes one meep
        # from the availability pool.  Each event carries ownership +
        # event identity; the ledger books balance row by row.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        account = _bard_account(result)
        assert account is not None
        accepted = [r for r in account["receipts"] if r["accepted"]]
        assert accepted
        # 35 chimes / 10s: 3 stock + 1 recharge = 4 meeps consumed.
        assert len(accepted) == 4
        assert all(r["amount"] == 1.0 for r in accepted)
        assert all(r["owner"] == "main" for r in accepted)
        assert all(r["kind"] in ("chimes", "meeps") for r in accepted)
        # Event identity: each row names its source event.
        assert all(
            r["source"] or (r.get("detail", {}) or {}).get("event_id") for r in accepted
        )
        # Ledger books balance: each row moves current by its signed
        # amount, and closing equals opening plus the accepted deltas.
        ordered = sorted(
            account["receipts"], key=lambda r: (float(r["time"]), int(r["sequence"]))
        )
        current = float(account["opening_current"])
        for row in ordered:
            signed = float(row["amount"]) * (
                -1.0 if row["operation"] in ("consume", "spend") else 1.0
            )
            assert float(row["current_after"]) == pytest.approx(
                float(row["current_before"]) + signed
            )
            if row["accepted"]:
                current = float(row["current_after"])
        assert float(account["closing_current"]) == pytest.approx(current)

    def test_non_meep_events_gain_nothing(self):
        # A fight with no autos (no meep-consumption events) yields no
        # accepted rows and an unchanged counter; Q casts are not meep
        # events and consume nothing.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0}, uptime=0.0)
        assert "on_hit_ability_passive" not in result["breakdown"]
        account = _bard_account(result)
        assert account is not None
        accepted = [r for r in account["receipts"] if r["accepted"]]
        assert accepted == []
        assert account["closing_current"] == account["opening_current"]

    def test_every_accepted_row_carries_owner_and_identity(self):
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        account = _bard_account(result)
        assert account is not None
        accepted = [r for r in account["receipts"] if r["accepted"]]
        assert all(r["owner"] == "main" for r in accepted)
        assert all(
            r["source"] or (r.get("detail", {}) or {}).get("event_id") for r in accepted
        )


# ---------------------------------------------------------------------------
# S4 — Permanent counter / availability
# ---------------------------------------------------------------------------


class TestPermanentCounter:
    def test_option_prices_meep_math_parse_time_no_repricing(self):
        # The seeded option is the parse-time price: the fight's meep
        # per-hit equals the seeded parse per-hit (mitigated by the
        # fight's 40 MR) and the meep count equals the seeded max_procs
        # (autos permitting) — never re-priced mid-fight by any ledger.
        for seed, per_hit, windowed in (
            (0, 30.0, 2),
            (35, 72.0, 4),
            (100, 150.0, 8),
            (200, 270.0, 8),
        ):
            _, abilities = _parse({"chimes": seed, "fight_duration_seconds": 10.0})
            result = _fight({"chimes": seed, "fight_duration_seconds": 10.0})
            row = result["breakdown"]["on_hit_ability_passive"]
            assert row["damage_per_hit"] == pytest.approx(
                _meep(abilities)["damage_per_hit"] * 100 / 140
            )
            assert row["count"] == windowed

    def test_one_rotation_uses_stock_only(self):
        # One-rotation mode prices the stocked meeps only (no fight
        # window): 35 chimes -> 3 meeps.
        _, abilities = _parse({"chimes": 35})
        result = _fight({"chimes": 35}, one_rotation=True)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert _meep(abilities)["max_procs"] == 3
        assert row["count"] == 3

    def test_chime_counter_permanent_no_expiry_or_decay(self):
        # The CHIME counter is permanent: no expiry/decay operations and
        # no consume of chimes; when no live events fire the counter is
        # unchanged (closing == opening).  The meep availability side
        # may consume (S3) — the permanence pin is the chime counter.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0}, uptime=0.0)
        account = _bard_account(result)
        assert account is not None
        declaration = account["declaration"]
        assert declaration["permanent"] is True
        operations = {r["operation"] for r in account["receipts"]}
        assert not operations & {"expiry", "decay"}
        assert account["closing_current"] == account["opening_current"]
        assert account["opening_current"] == 35

    def test_meep_availability_documented(self):
        # The meep availability (stock + recharge) is documented beside
        # the counter: the 35-chime seed declares stock 3, recharge 7.0,
        # and the 10s window's max_procs 4.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        account = _bard_account(result)
        assert account is not None
        availability = _availability(account)
        assert availability["stock"] == 3
        assert availability["recharge"] == pytest.approx(7.0)
        assert availability["max_procs"] == 4


# ---------------------------------------------------------------------------
# S5 — Stat and public ledger receipts
# ---------------------------------------------------------------------------


class TestLedgerReceipts:
    def test_mana_account_coexists_today(self):
        # The mana account is real and unchanged — spend receipts visible,
        # resource_spent / resource_remaining computed — and the additive
        # chime/meep sub-section coexists beside it once wired.
        #
        # Roadmap session 2 (2026-08-20): W and R are now modeled (they
        # carry a real cached cooldown/cost, per module_helpers.no_damage),
        # so this fixture's cast_order=["Q", "W", "R"] puts all three on
        # the shared timed-cast timeline — one Q (60), one W (70), one R
        # (100) at the front of the fight, then a second Q (60) once its
        # cooldown is back up: 290 total spent of the 300 starting pool.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        assert ledger["opening_current"] == pytest.approx(300.0)
        spends = [r for r in ledger["receipts"] if r["operation"] == "spend"]
        assert len(spends) == 4
        assert all(r["accepted"] for r in spends)
        by_slot = {r["detail"]["slot"]: r["amount"] for r in spends}
        assert [r["detail"]["slot"] for r in spends] == ["Q", "W", "R", "Q"]
        assert by_slot["W"] == pytest.approx(70.0)
        assert by_slot["R"] == pytest.approx(100.0)
        assert sum(1 for s in spends if s["detail"]["slot"] == "Q") == 2
        assert all(
            r["amount"] == pytest.approx(60.0)
            for r in spends
            if r["detail"]["slot"] == "Q"
        )
        assert result["resource_spent"] == pytest.approx(290.0)
        assert result["resource_remaining"] == pytest.approx(10.0)

    def test_mana_receipts_are_resource_receipt_shaped(self):
        # The mana account's rows are ResourceReceipt-shaped — the shape
        # the chime/meep account must match (S6 contract).
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        ledger = result["resource_ledger"]
        for row in ledger["receipts"]:
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

    def test_bard_ledger_sub_section_kind_and_receipt_shape(self):
        # The chime/meep account: kind "chimes"/"meeps", ResourceReceipt-
        # shaped rows, the typed rule declaration, and the availability
        # rows — with the mana account surviving beside it.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        account = _bard_account(result)
        assert account is not None
        assert account["kind"] in ("chimes", "meeps")
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
        assert declaration["meep_base"] == pytest.approx(30.0)
        assert declaration["meep_per_tier"] == pytest.approx(6.0)
        assert declaration["chimes_per_tier"] == 5
        assert declaration["meep_ap_ratio"] == pytest.approx(0.40)
        assert declaration["permanent"] is True
        assert declaration.get("source")  # provenance
        # The mana account (real cast admission) survives beside it.
        assert result["resource_ledger"]["kind"] == "mana"

    def test_bard_ledger_visible_in_api_payload(self):
        response = _api({"chimes": 35})
        assert response.status_code == 200
        body = response.get_json()
        account = _bard_account(body)
        assert account is not None
        assert account["kind"] in ("chimes", "meeps")


# ---------------------------------------------------------------------------
# S6 — Malformed/missing event data fail-closed
# ---------------------------------------------------------------------------


class TestMalformedEventsFailClosed:
    def test_chime_collection_events_fail_closed(self):
        # Chime-collection simulation (spawn timing / collection rate) is
        # NOT modeled — the model cannot farm chimes mid-fight; an
        # authored chime-collection event receipts a named fail-closed
        # denial and gains the counter nothing.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        account = _bard_account(result)
        assert account is not None
        denials = [r for r in account["receipts"] if not r["accepted"]]
        assert any("chime" in r["reason"].lower() for r in denials)
        assert not [
            r
            for r in account["receipts"]
            if r["accepted"] and "chime" in str(r["source"]).lower()
        ]

    def test_meep_slow_and_splash_events_fail_closed(self):
        # The meep slow (5+ chimes) and the 15+ chime splash/cone are
        # unmodeled boundaries (module ASSUMPTIONS); authored events
        # naming them receipt named fail-closed denials and invent no
        # damage or gains.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        account = _bard_account(result)
        assert account is not None
        denials = [r for r in account["receipts"] if not r["accepted"]]
        assert any(
            "slow" in r["reason"].lower() or "splash" in r["reason"].lower()
            for r in denials
        )

    def test_event_without_identity_fails_closed(self):
        # A chime/meep event without event identity: named fail-closed
        # receipt, no gain; no invented gain can carry an empty identity.
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        account = _bard_account(result)
        assert account is not None
        denials = [r for r in account["receipts"] if not r["accepted"]]
        assert any("identity" in r["reason"].lower() for r in denials)
        accepted = [r for r in account["receipts"] if r["accepted"]]
        assert all(
            r["source"] or (r.get("detail", {}) or {}).get("event_id") for r in accepted
        )


# ---------------------------------------------------------------------------
# S7 — Score/receipt parity
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_seeded_score_receipt_parity(self):
        # The seeded fight's breakdown/cast/receipt surface agrees
        # between the full walk and the compiled score path.  The
        # score-only cast_timeline carries the cast projection
        # (time/slot/name/ordinal/resource_cost); the full walk adds the
        # resource-before/restored/after fields on top — the shared rows
        # and the mana ledger are identical.
        for seed in (0, 35, 100, 200):
            full = _fight({"chimes": seed, "fight_duration_seconds": 10.0})
            scored = _fight(
                {"chimes": seed, "fight_duration_seconds": 10.0}, score_only=True
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

    def test_bard_ledger_score_parity(self):
        full = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        scored = _fight({"chimes": 35, "fight_duration_seconds": 10.0}, score_only=True)
        assert _bard_account(full) is not None
        assert _bard_account(full) == _bard_account(scored)


# ---------------------------------------------------------------------------
# S8 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_meep_damage_formula_unchanged(self):
        # Wiki reference values at 0 AP: 30 + 6 per 5 chimes.
        for chimes, expected in (
            (5, 36.0),
            (15, 48.0),
            (25, 60.0),
            (35, 72.0),
            (50, 90.0),
            (100, 150.0),
        ):
            _, abilities = _parse({"chimes": chimes})
            assert _meep(abilities)["damage_per_hit"] == pytest.approx(expected)
        _, abilities = _parse({"chimes": 35}, ap=100.0)
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(112.0)

    def test_stock_table_unchanged(self):
        # Every boundary of {{pp|1 to 9 for 9|0;10;30;50;65;80;90;95;100}}
        # — stock without a fight window.
        for chimes, stock in (
            (0, 1),
            (9, 1),
            (10, 2),
            (29, 2),
            (30, 3),
            (49, 3),
            (50, 4),
            (64, 4),
            (65, 5),
            (79, 5),
            (80, 6),
            (89, 6),
            (90, 7),
            (94, 7),
            (95, 8),
            (99, 8),
            (100, 9),
        ):
            _, abilities = _parse({"chimes": chimes})
            assert _meep(abilities)["max_procs"] == stock

    def test_recharge_table_unchanged(self):
        # Every boundary of {{pp|8 to 4 for 5|0;20;40;55;70}} over a 10s
        # window: max_procs = stock + floor(10 / recharge).
        for chimes, expected in (
            (0, 1 + 1),
            (19, 2 + 1),
            (20, 2 + 1),
            (39, 3 + 1),
            (40, 3 + 1),
            (54, 4 + 1),
            (55, 4 + 2),
            (69, 5 + 2),
            (70, 5 + 2),
        ):
            _, abilities = _parse({"chimes": chimes, "fight_duration_seconds": 10.0})
            assert _meep(abilities)["max_procs"] == expected

    def test_max_procs_caps_empowered_autos_unchanged(self):
        # The fight engine empowers the FIRST max_procs autos (earliest
        # swings) and plain autos beyond the pool: 10s at AS 0.8 -> 8
        # autos; 35 chimes -> 4 meeps at 0/1.25/2.5/3.75; 100 chimes ->
        # max_procs 11 but only 8 autos land (autos cap the count).
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 4
        assert [e["time"] for e in row["damage_events"]] == [0.0, 1.25, 2.5, 3.75]
        result = _fight({"chimes": 100, "fight_duration_seconds": 10.0})
        assert result["breakdown"]["auto_attacks"]["count"] == 8
        assert result["breakdown"]["on_hit_ability_passive"]["count"] == 8
        # User repro: 10 chimes, 7s timed fight -> exactly 2 meep autos
        # (stock 2 + floor(7/8) = 0 recharges), 42 raw each at 0 AP.
        result = _fight({"chimes": 10, "fight_duration_seconds": 7.0}, duration=7.0)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 2
        assert row["damage_per_hit"] == pytest.approx(42.0 * 100 / 140)

    def test_q_unchanged(self):
        # Q: one clean magic hit on the primary target, sourced from the
        # cached leveling rows (80..240 flat + 80% AP), cooldown 7,
        # 60 mana.
        stats, abilities = _parse({"chimes": 35})
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _resolve("Q", "Magic Damage", 4, stats)
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(240.0)
        assert abilities["Q"]["cooldown"] == pytest.approx(7.0)
        assert abilities["Q"]["resource_cost"] == pytest.approx(60.0)
        assert abilities["Q"]["resource_type"] == "MANA"
        assert abilities["Q"]["damage_type"] == "magic"
        _, abilities = _parse({"chimes": 35}, ap=100.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(
            _resolve("Q", "Magic Damage", 4, dict(_stats(), ability_power=100.0))
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(320.0)

    def test_w_e_r_zero_damage_rows_unchanged(self):
        # W (ally heal), E (portal), R (stasis) deal no ENEMY damage.
        # Roadmap session 2 (2026-08-20): all three now emit an explicit
        # zero-damage state row (module_helpers.no_damage) rather than
        # staying absent — the meep slow and splash remain named unmodeled
        # assumptions regardless.
        _, abilities = _parse({"chimes": 35})
        for slot in ("W", "E", "R"):
            assert slot in abilities
            assert abilities[slot]["total_raw"] == 0.0
        result = _fight({"chimes": 35, "fight_duration_seconds": 10.0})
        # This fixture's cast_order is ["Q", "W", "R"] (E excluded from
        # the shared cast timeline by this file's _fight default), so W
        # and R now surface as zero-damage rows in the breakdown beside
        # the P3-3Y informational chimes row; E does not cast here and so
        # has no breakdown row of its own.
        assert set(result["breakdown"]) == {
            "Q",
            "W",
            "R",
            "auto_attacks",
            "on_hit_ability_passive",
            "chimes",
        }
        assert result["breakdown"]["W"]["total_damage"] == 0.0
        assert result["breakdown"]["R"]["total_damage"] == 0.0
        meta = get_champion_options_meta("Bard")
        assert any("Meep slow" in text for text in meta["assumptions"])
        assert any("splash" in text for text in meta["assumptions"])
        assert any("W (heal)" in text for text in meta["assumptions"])
        assert any("E (portal)" in text for text in meta["assumptions"])
        assert any("R (stasis)" in text for text in meta["assumptions"])


# ---------------------------------------------------------------------------
# S9 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (contract 9):
#   .venv/bin/python -m pytest tests/test_bard_chimes_ledger.py \
#     tests/test_aurelion_sol_stardust_ledger.py tests/test_senna_souls_ledger.py \
#     tests/test_rengar_ferocity_ledger.py tests/test_state_lifecycle.py \
#     tests/test_state_lifecycle_consumers.py tests/test_resource_ledger.py \
#     tests/test_resource_ledger_consumers.py \
#     tests/test_resource_ledger_champion_consumers.py \
#     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#     tests/test_mana_restore_refund.py tests/test_app.py
# Bard / chime / meep grep surface (contract 9), run separately:
#   tests/test_bard.py tests/test_damage.py tests/test_e8_followup_hooks.py \
#     tests/test_e8_support.py tests/test_e1_healing_b5.py \
#     tests/test_zhonya_packet.py tests/test_interaction_atoms.py
