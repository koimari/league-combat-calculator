"""P2 Slice 5 — Gangplank W (Remove Scurvy) champion cleanse (test-matrix
owner: RLM-2 C).

Focused TDD matrix for Gangplank's W (Remove Scurvy) champion cleanse.
CURRENT RUNTIME FACTS (verified before pinning):

- The module (``src/calculator/champions/gangplank.py``) ships
  ``_remove_scurvy`` as a ``no_damage`` stub: name "Remove Scurvy", rank,
  cooldown 22/20/18/16/14 by rank, MANA cost 60/70/80/90/100, cast_time
  0.25, ``total_raw`` 0.0 and no parts ("Heal and cleanse only; no
  outgoing damage is listed.").
- There is NO ``w`` option today: OPTIONS declares exactly
  p_procs / r_fire_at_will / r_deaths_daughter; the API rejects any
  ``w*`` champion option with a named 400 ("champion_options contains
  unknown option w").  Passing a ``w*`` seed to the module parse path is
  silently ignored (the option gate lives at the API/scenario boundary).
- The cached W rows (data/champions.json "Gangplank", revision-pinned):
  "Heal" = 45/70/95/120/145 flat + 90% AP + 13% missing health; cost
  60..100; cooldown 22..14 (affected by CDR); castTime "0.25";
  targeting "Auto"; affects "Self"; resource MANA; notes carry the
  airborne displacement-override note ("can remove the underlying stun
  from airborne, but a blink or dash ability is required to override
  the displacement").
- THE HEAL IS ALREADY AUTHORED (divergence from the brief's framing):
  ``healing.derive_self_healing``'s Gangplank branch (owned by the E1/E9
  ledger lineage; ("Gangplank", "W") in ``_MODULE_AUTHORED_HEAL_SLOTS``)
  emits ONE ``champion_ability`` heal per accepted W cast at the CAST
  START time with a live ``amount_formula`` = flat + 90% AP + 13% of
  current missing health, re-priced by the survival ledger from the
  fight state at the landing time.  It fires with NO option (the brief's
  "heal as a separate authored effect" is already true); it is a SEPARATE
  receipt (public ``healing_events`` entry + ``healing_received``) from
  any cleanse.
- PINNED ACTUAL (flagged for the coordinator): the authored heal rides
  the walk's attacker-state gate — while the caster is crowd-controlled
  the heal is skipped with ``attacker_state_blocked`` and never lands
  (Remove Scurvy cannot currently be cast while CC'd, which defeats the
  spell's purpose).  The P2-5 cleanse wiring must decide the
  castability carve-out (the Slice 4 self-scope precedent: QSS/Mercurial
  utility cleanses dispatch BEFORE the attacker gate and are castable
  while disabled but NOT under suppression).
- There is NO cleanse: no ``cleanse``/``cleanse_use``/``cleanse_denied``
  survival rows, no utility cleanse events (``cleanse.event_count`` 0),
  no crowd-control truncation, no one-use latch.  The Slice 4 kernel
  (``cleanse_eligibility.py``) owns the typed contract the W must ride;
  ``resolve_cleanse_item("Remove Scurvy")`` FAILS CLOSED today with a
  KeyError naming the source (the "unavailable source" denial) — the
  completion must declare the champion cleanse source.
- Score fail-closed gate (already generic):
  ``unrepresentable_template_receipt`` returns ``support_kind=cleanse``
  for cleanse-kind templates and ``support_cleanse`` for heal packets
  carrying the cleanse marker — the compiled score path can never
  silently re-price a cleanse (HANDOVER section 9 rule).

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (cached W rows; the module parse
      receipt; the no-outgoing-damage pin; the already-authored heal
      receipt; the absent typed heal+cleanse declaration xfailed).
  S2  Absent option (no w option -> the W stays the no_damage stub and
      the cleanse never fires implicitly; the API boundary named-400
      pinned actual; the acceptance contract xfailed).
  S3  Explicit activation (the w option activates the cleanse at an
      explicit time; the heal's missing-health evaluation point pinned;
      separate heal + cleanse receipts; the Slice 4 decision shape).
  S4  Target + timing (Self scope; activation time vs the cast
      timeline; the one-use latch and use_spent).
  S5  Crowd control + suppression gates (active-control truncation;
      control landing after activation untouched; suppression /
      unknown kinds -> named fail-closed denials; the airborne
      displacement-override named boundary).
  S6  Interval truncation (historical downtime remains; an active
      interval ends at the activation; the kernel the W rides).
  S7  Named denials (missing identity, invalid target, unavailable
      source, unsupported control/suppression state, unsupported
      spatial or score behavior).
  S8  Score fail-closed behavior (the generic gate pins; the W wiring
      contract xfailed: never silently re-price).
  S9  Mode parity (full vs score_only agree today; the named-divergence
      contract xfailed).
  S10 Unchanged boundaries (P/Q/E/R damage, the existing options, the
      mana ledger — the W cast DOES spend mana 60..100 by rank today —
      cast timing, item-cleanse regression surface).
  S11 Regression surface: the mandated sanity list (footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows — no literal damage constants.  The W heal/cost/cooldown
arrays ARE the values under test (the cached rows the typed declaration
must publish), so they appear as pinned cache rows (the K'Sante matrix
precedent).  The option spelling below is a pinned CANDIDATE (one
constant, ``_W_OPTION_KEY``); the coordinator's final spelling is the
#1 contract ambiguity reported to the parent.
"""

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.slotlib import extract_named
from src.calculator.cleanse_eligibility import (
    CleanseEligibility,
    resolve_cleanse_item,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.healing import derive_self_healing

# MERGE: the shared healing readers moved out of ``healing.py`` into
# ``healing_helpers.py`` (HEALING-API); ``healing.py`` only loads
# declarations and sorts receipts now.
from src.calculator.healing_helpers import leveling_ratio
from src.calculator.participant_timeline import Combatant
from src.calculator.survival.compile import unrepresentable_template_receipt
from tests.app_config import app_config
from tests.survival_probe import simulate_survival

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_GANPLANK_DATA = _CHAMPION_DATA["Gangplank"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P2-5 coordinator wires the typed W declaration + the w option;
# genuinely-absent mechanics are xfailed with this reason.
_AWAIT = "awaiting P2-5 wiring"

# Pinned CANDIDATE option spelling (contract ambiguity #1 for the
# coordinator): the explicit cleanse-activation time in seconds.  All
# contract tests read this one constant; the coordinator's final spelling
# is a one-line adjustment.
_W_OPTION_KEY = "w_time"

# The cached W rows the typed declaration must publish (values under
# test — pinned as cache evidence, never literal damage constants).
_W_HEAL_FLAT = [45, 70, 95, 120, 145]
_W_HEAL_AP_PERCENT = 90
_W_HEAL_MISSING_PERCENT = 13
_W_COST = [60, 70, 80, 90, 100]
_W_COOLDOWN = [22, 20, 18, 16, 14]
_W_CAST_TIME = 0.25


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
        "is_melee": True,
        "lethality": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 100.0,
        "ability_power": 100.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 40.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 300.0,
        "resource_regen_per_second": 0.0,
        "level": _LEVEL,
        "health": 2000.0,
        "max_health": 2000.0,
    }


def _parse(option: dict | None = None, *, ranks: dict | None = None):
    stats = _stats()
    abilities = parse_champion_abilities(
        get_champion("Gangplank"),
        _LEVEL,
        float(stats["ability_power"]),
        ability_ranks=ranks or _RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option,
    )
    return stats, abilities


def _fight(
    option: dict | None = None,
    *,
    duration: float = 10.0,
    one_rotation: bool = False,
    score_only: bool = False,
    ranks: dict | None = None,
) -> dict:
    stats, abilities = _parse(option, ranks=ranks)
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=_TARGET_MAX_HP,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=duration,
            auto_attack_uptime=0.0,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=["Q", "W", "E", "R"],
        ),
        score_only=score_only,
        champion_options=dict(option or {}),
    )


def _w_ability() -> dict:
    return _GANPLANK_DATA["abilities"]["W"][0]


def _leveling(attribute: str) -> dict:
    for effect in _w_ability().get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"no W leveling {attribute!r}")


def _w_flat(rank: int) -> float:
    return float(_leveling("Heal")["modifiers"][0]["values"][rank - 1])


def _heal_formula(rank: int, ap: float, missing: float) -> float:
    """The pinned Remove Scurvy heal: flat + 90% AP + 13% missing health."""
    return (
        _w_flat(rank)
        + _W_HEAL_AP_PERCENT / 100.0 * ap
        + (_W_HEAL_MISSING_PERCENT / 100.0) * missing
    )


@contextlib.contextmanager
def _testing_client():
    """A flask test client with TESTING enabled, restored afterwards.

    The flask app config is process-global: test_app.py's rate-limit tests
    rely on ``TESTING`` being False (the limiter is bypassed under
    TESTING), so this file must never leave the flag set.
    """
    with app_config(TESTING=True):
        yield app_module.app.test_client()


def _app_combat(
    option: dict | None,
    enemy_ranks: dict,
    *,
    duration: float = 6.0,
    enemy: str = "Ahri",
) -> dict:
    """The app-level combat payload (full pipeline + survival walk)."""
    with _testing_client() as client:
        response = client.post(
            "/api/calculate",
            json={
                "champion": "Gangplank",
                "level": _LEVEL,
                "items": [],
                "role": "mid",
                "ability_ranks": _RANKS,
                "fight_mode": "time_based",
                "fight_duration": duration,
                "include_auto_attacks": False,
                "target_health": _TARGET_MAX_HP,
                "target_armor": 50,
                "target_mr": 40,
                "champion_options": option or {},
                "enemies": [
                    {
                        "champion": enemy,
                        "level": _LEVEL,
                        "items": [],
                        "ability_ranks": enemy_ranks,
                    }
                ],
            },
        )
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _main_survival(combat: dict) -> dict:
    return combat["participants"][0]["survival"]


def _main_heals(combat: dict) -> list[dict]:
    return [
        e
        for e in combat.get("healing_events", [])
        if e.get("attacker") == "main" and e.get("source") == "Remove Scurvy"
    ]


def _enemy_damage_before(combat: dict, time: float) -> float:
    return sum(
        float(e.get("damage", 0.0) or 0.0)
        for e in combat.get("events", [])
        if e.get("attacker") != "main" and float(e.get("time", 99.0)) <= time
    )


def _dummy_combatant(participant_id: str, team: str, health: float = 3000.0):
    defenses = StartingDefenses(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.0,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health},
        defenses=defenses,
    )


def _control_packet(
    time: float, kind: str, duration: float, *, source: str = "E"
) -> dict:
    return {
        "time": time,
        "damage": 0.0,
        "damage_type": "magic",
        "attacker": "enemy",
        "target": "main",
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "crowd_control",
        "sequence": 0,
        "_event_id": f"cc-{source}-{time}",
        "cc_kind": kind,
        "cc_duration": duration,
    }


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_w_heal_rows_pinned_in_cache(self):
        # The W "Heal" leveling row is 45/70/95/120/145 flat + 90% AP +
        # 13% missing health; cost 60..100; cooldown 22..14; castTime
        # 0.25; Self/Auto/MANA.  These are the values the P2-5 typed
        # declaration must publish (the brief's contract #1).
        heal = _leveling("Heal")
        assert heal["modifiers"][0]["values"] == _W_HEAL_FLAT
        assert heal["modifiers"][1]["values"] == [_W_HEAL_AP_PERCENT] * 5
        assert heal["modifiers"][1]["units"] == ["% AP"] * 5
        assert heal["modifiers"][2]["values"] == [_W_HEAL_MISSING_PERCENT] * 5
        assert heal["modifiers"][2]["units"] == ["% missing health"] * 5
        w = _w_ability()
        assert w["cost"]["modifiers"][0]["values"] == _W_COST
        assert w["cooldown"]["modifiers"][0]["values"] == _W_COOLDOWN
        assert w["cooldown"]["affectedByCdr"] is True
        assert w["castTime"] == str(_W_CAST_TIME)
        assert w["targeting"] == "Auto"
        assert w["affects"] == "Self"
        assert w["resource"] == "MANA"
        assert w["damageType"] is None

    def test_w_airborne_displacement_override_note_pinned(self):
        # The airborne displacement-override note (the brief's contract
        # #5 named boundary): the stun underneath an airborne is removed,
        # the displacement is not.
        notes = _w_ability()["notes"]
        assert "airborne" in notes
        assert "dash ability is required to override" in notes

    def test_w_heal_contract_values_recomputed(self):
        # Recompute through the module's typed extractor: extract_named
        # resolves flat + 90% AP (the missing-health unit has no resolver
        # and contributes 0 at parse time); _leveling_ratio reads the
        # sourced 13% missing-health modifier (the healing.py path that
        # authors the heal today).
        w = _w_ability()
        for rank in range(1, 6):
            assert extract_named(w, "Heal", rank, {"ability_power": 100.0}) == (
                _w_flat(rank) + _W_HEAL_AP_PERCENT
            )
            assert leveling_ratio(w, "Heal", "missing health", rank) == (
                _W_HEAL_MISSING_PERCENT
            )
        # The full formula the declaration must publish.
        assert _heal_formula(5, 100.0, 1000.0) == pytest.approx(145.0 + 90.0 + 130.0)

    def test_w_public_receipt_present_in_parse(self):
        # The W public receipt at parse level (the no_damage stub): name,
        # rank, cooldown, cost, cast time, zero total and no parts.
        _, abilities = _parse()
        w = abilities["W"]
        assert w["name"] == "Remove Scurvy"
        assert w["rank"] == 5
        assert w["cooldown"] == pytest.approx(14.0)
        assert w["resource_type"] == "MANA"
        assert w["resource_cost"] == pytest.approx(100.0)
        assert w["cast_time"] == pytest.approx(_W_CAST_TIME)
        assert w["total_raw"] == 0.0
        assert w["parts"] == ()
        assert "Heal and cleanse only" in w["detail"]

    def test_w_no_outgoing_damage_pin(self):
        # The no-outgoing-damage pin (brief contract #1): W total_raw 0
        # and no damage row in the fight result for every rank and both
        # fight modes.
        for rank in range(1, 6):
            _, abilities = _parse(ranks={**_RANKS, "W": rank})
            assert abilities["W"]["total_raw"] == 0.0
            assert abilities["W"]["parts"] == ()
        for one_rotation in (True, False):
            result = _fight({}, one_rotation=one_rotation)
            row = result["breakdown"]["W"]
            assert row["total_raw"] == 0
            assert row["total_damage"] == 0.0
            assert "damage_events" not in row

    def test_w_heal_receipt_already_authored(self):
        # The heal IS already authored (divergence from the brief's
        # "separate authored effects" framing — the heal half is true):
        # one champion_ability heal per W cast with the live formula,
        # separate from any cleanse.
        heals = derive_self_healing(
            get_champion("Gangplank"),
            {"level": 18, "health": 2000.0, "ability_power": 100.0},
            {"W": {"rank": 5}},
            [],
            [{"slot": "W", "time": 1.0}],
            5.0,
        )
        assert len(heals) == 1
        heal = heals[0]
        assert heal["time"] == pytest.approx(1.0)
        assert heal["source"] == "Remove Scurvy"
        assert heal["kind"] == "champion_ability"
        assert heal["actor_wide"] is True
        # Live missing-health evaluation: at 50% health, 145 + 90 + 130.
        assert heal["amount_formula"](1000.0, 2000.0) == pytest.approx(365.0)
        # No heal for a fight with no W cast.
        assert (
            derive_self_healing(
                get_champion("Gangplank"),
                {"level": 18, "health": 2000.0, "ability_power": 100.0},
                {"Q": {"rank": 5}},
                [],
                [{"slot": "Q", "time": 1.0}],
                5.0,
            )
            == []
        )

    def test_w_heal_receipt_in_fight_result(self):
        # The heal's public receipt in the fight result (brief contract
        # #3's "separate heal receipt (kind, amount, owner, time)"):
        # landing at the W cast start time 0.25, owner main, amount =
        # flat + 90% AP + 13% of the missing health at that time.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 0, "R": 0})
        heals = _main_heals(combat)
        assert heals, "Remove Scurvy heal missing"
        heal = heals[0]
        assert heal["time"] == pytest.approx(0.25)
        assert heal["attacker"] == "main"
        assert heal["event_id"].startswith("main:heal:")
        ap = float(combat["participants"][0]["stats"]["ability_power"])
        taken_before = _enemy_damage_before(combat, 0.25)
        assert heal["raw_amount"] == pytest.approx(
            _heal_formula(5, ap, taken_before), abs=0.2
        )
        assert heal["applied_amount"] > 0.0
        assert _main_survival(combat)["healing_received"] == pytest.approx(
            heal["applied_amount"]
        )

    def test_w_source_receipts_pin_wiki_revisions(self):
        # Source receipts pin the wiki revisions the cached rows came from.
        sources = {
            row["label"]: row
            for row in get_champion_options_meta("Gangplank")["sources"]
        }
        assert sources["Gangplank parent entry"]["url"].endswith("/en-us/Gangplank")
        assert sources["Gangplank parent entry"]["revision_id"] == 4002542
        assert sources["Gangplank W template"]["revision_id"] == 2864237

    def test_w_typed_declaration_publishes_heal_and_cleanse_contract(self):
        # P2-5 contract: the module exposes a typed W declaration (the
        # KSANTE_PATH_MAKER_RULE precedent) publishing the heal (flat
        # row, 90% AP, 13% missing health), cooldown/cost rows, the
        # self target scope and the airborne-override boundary — with a
        # public receipt.  Absent today (the module ships only the
        # no_damage stub).
        import src.calculator.champions.gangplank as gp_module

        rule = getattr(gp_module, "REMOVE_SCURVY_RULE", None)
        assert rule is not None, "typed W declaration absent"
        receipt = rule.public_receipt() if hasattr(rule, "public_receipt") else rule
        assert receipt["heal"]["flat"] == _W_HEAL_FLAT
        assert receipt["heal"]["ap_percent"] == _W_HEAL_AP_PERCENT
        assert receipt["heal"]["missing_health_percent"] == _W_HEAL_MISSING_PERCENT
        assert receipt["cooldown"] == _W_COOLDOWN
        assert receipt["cost"] == _W_COST
        assert receipt["target_scope"] == "self"
        assert "airborne" in receipt.get("excluded_control_kinds", ())
        assert receipt["source"]  # provenance on the declaration


# ---------------------------------------------------------------------------
# S2 — Absent option
# ---------------------------------------------------------------------------


class TestAbsentOption:
    def test_options_meta_has_exactly_three_options(self):
        # OPTIONS declares exactly p_procs / r_fire_at_will /
        # r_deaths_daughter (byte-identical); no w* option exists.
        meta = get_champion_options_meta("Gangplank")
        by_key = {option["key"]: option for option in meta["options"]}
        assert set(by_key) == {"p_procs", "r_fire_at_will", "r_deaths_daughter"}
        assert by_key["p_procs"] == {
            "key": "p_procs",
            "type": "int",
            "default": 0,
            "min": 0,
            "max": 10,
            "label": "Trial by Fire procs",
        }
        assert by_key["r_fire_at_will"] == {
            "key": "r_fire_at_will",
            "type": "bool",
            "default": False,
            "label": "Cannon Barrage Fire at Will upgrade",
        }
        assert by_key["r_deaths_daughter"] == {
            "key": "r_deaths_daughter",
            "type": "bool",
            "default": False,
            "label": "Cannon Barrage Death's Daughter upgrade",
        }

    def test_no_w_option_w_stays_no_damage_stub(self):
        # No w option -> the W stays the no_damage stub (brief contract
        # #2): the parse entry and the fight result are byte-identical
        # with and without other options, and the cast timeline still
        # books the W cast (the heal keeps riding it).
        _, plain = _parse()
        _, seeded = _parse({"p_procs": 2})
        assert plain["W"] == seeded["W"]
        result = _fight({}, one_rotation=True)
        (w_cast,) = [c for c in result["cast_timeline"] if c["slot"] == "W"]
        assert w_cast["time"] == pytest.approx(0.0)
        assert w_cast["name"] == "Remove Scurvy"

    def test_no_w_option_w_cast_is_the_implicit_activation(self):
        # P2-5 contract (coordinator's decision): NO user option — the W
        # cast IS the cleanse activation (the source supports the cast,
        # not an optional toggle).  With a W cast (rank 5) the cleanse
        # fires at the cast time, the charm truncates at it, and the heal
        # lands with it (castable while disabled).  W rank 0 -> no cast
        # -> no packet -> nothing activates.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        survival = _main_survival(combat)
        assert survival["cleanse"]["activation_time"] == pytest.approx(0.25)
        assert survival["cleanse"]["decision"]["eligible"] is True
        assert survival["action_downtime"] == pytest.approx(0.25)
        assert survival["crowd_control_until"] == pytest.approx(0.25)
        assert survival["cleanse_use"]["uses_after"] == 0
        assert (
            combat["utility_outcomes"]["participants"]["main"]["cleanse"]["event_count"]
            == 1
        )
        (heal,) = _main_heals(combat)
        assert heal.get("skipped_reason") is None
        assert heal["raw_amount"] > 0.0

    def test_api_rejects_w_option_today_with_named_400(self):
        # Pinned actual (the option is genuinely absent at the API
        # boundary): every candidate w* key gets a named 400.  This flips
        # when the P2-5 option lands (the acceptance contract is pinned
        # by the xfail below).
        with _testing_client() as client:
            responses = []
            responses.extend(
                (
                    key,
                    client.post(
                        "/api/calculate",
                        json={
                            "champion": "Gangplank",
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
                            "champion_options": {key: True},
                        },
                    ),
                )
                for key in ("w", "w_time", "w_use", "w_cleanse")
            )
        for key, response in responses:
            assert response.status_code == 400
            assert response.get_json()["error"] == (
                f"champion_options contains unknown option {key}"
            )

    def test_api_w_cast_activates_cleanse_no_option(self):
        # P2-5 acceptance contract (coordinator's decision): NO user
        # option — the W cast IS the activation.  /api/config still
        # declares exactly the three existing options (the w_time
        # candidate stays rejected), and an API fight with a W cast
        # activates the cleanse.
        with _testing_client() as client:
            config = client.get("/api/config").get_json()
        options = config["champion_options"]["Gangplank"]["options"]
        by_key = {option["key"]: option for option in options}
        assert set(by_key) == {"p_procs", "r_fire_at_will", "r_deaths_daughter"}
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 0, "R": 0})
        assert _main_survival(combat).get("cleanse") is not None


# ---------------------------------------------------------------------------
# S3 — Explicit activation
# ---------------------------------------------------------------------------


class TestExplicitActivation:
    def test_w_heal_missing_health_evaluation_point_pinned(self):
        # The heal's missing-health evaluation point (brief contract
        # #3's ambiguity): the survival ledger re-prices the live
        # amount_formula at the W cast start time from the fight state
        # (max_health - current_health) — the damage applied before the
        # cast.  Pinned with a no-CC enemy so the heal lands.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 0, "R": 0})
        (heal,) = _main_heals(combat)
        survival = _main_survival(combat)
        missing = float(survival["max_health"]) - (
            float(survival["max_health"]) - _enemy_damage_before(combat, 0.25)
        )
        ap = float(combat["participants"][0]["stats"]["ability_power"])
        assert heal["raw_amount"] == pytest.approx(
            _heal_formula(5, ap, missing), abs=0.2
        )

    def test_w_option_activates_cleanse_at_explicit_time(self):
        # P2-5 contract: the W cast authors the cleanse activation at
        # the cast time (no user option — the cast IS the activation);
        # the heal amount = flat + 90% AP + 13% MISSING health computed
        # from the fight state at the activation; a separate heal
        # receipt and a separate cleanse receipt both appear.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        survival = _main_survival(combat)
        cleanse = survival["cleanse"]
        assert cleanse["activation_time"] == pytest.approx(0.25)
        assert cleanse["decision"]["eligible"] is True
        heals = _main_heals(combat)
        assert heals
        assert heals[0]["applied_amount"] > 0.0

    def test_w_heal_and_cleanse_are_separate_receipts(self):
        # P2-5 contract: the heal and the cleanse stay SEPARATE effects
        # (brief contract #3) — the cleanse decision receipt lives on the
        # survival row (decision/recipient/use shape), the heal remains
        # its own healing_events entry, and the heal fires even when no
        # control is active (unconditional heal).  The heal half is true
        # today; the cleanse receipt half is absent.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 0, "R": 0})
        survival = _main_survival(combat)
        cleanse = survival["cleanse"]
        assert cleanse["decision"]["reason"] == "control_not_active"
        assert cleanse["use_consumed"] is True
        assert _main_heals(combat)  # the separate heal receipt still lands

    def test_w_cleanse_receipt_uses_slice4_shape(self):
        # P2-5 contract: the W cleanse receipt carries the Slice 4
        # decision field set (the acceptance matrix's exact shape) plus
        # the caster ``cleanse_use`` receipt.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        survival = _main_survival(combat)
        cleanse = survival["cleanse"]
        for field in (
            "eligible",
            "reason",
            "item",
            "activation_time",
            "target",
            "active_controls_before",
            "removed_controls",
            "rejected_controls",
            "intervals_after",
            "downtime_before",
            "downtime_after",
            "use_consumed",
        ):
            assert field in cleanse, field
        use = survival["cleanse_use"]
        assert use["uses_before"] == 1
        assert use["uses_after"] == 0
        assert use["activations"] == 1


# ---------------------------------------------------------------------------
# S4 — Target + timing + one-use
# ---------------------------------------------------------------------------


class TestTargetAndTiming:
    def test_kernel_self_scope_denies_foreign_target(self):
        # Kernel evidence (PASS): the Slice 4 kernel already implements
        # the self-scope contract the W must ride — a self declaration
        # denies a packet whose recipient is not the holder with the
        # named target_not_selected reason, consuming nothing.
        declaration = {
            "item": "Remove Scurvy",
            "active_name": "Remove Scurvy",
            "target_scope": "self",
            "excluded_control_kinds": ("airborne",),
            "cooldown_seconds": None,
            "cooldown_source_gap": True,
            "heal": None,
            "movement": None,
        }
        action = SimpleNamespace(
            time=1.0,
            source_key="Remove Scurvy",
            sequence=0,
            event_id="w:0",
            target="ally",
            holder="main",
            active_controls=[],
        )
        decision = CleanseEligibility(declaration=declaration).decide(action)
        assert decision.eligible is False
        assert decision.reason == "target_not_selected"
        assert decision.use_consumed is False

    def test_w_cleanse_targets_caster_self(self):
        # P2-5 contract: the W cleanse targets the caster (Self scope) —
        # the decision target equals the caster participant id, the
        # declaration's target_scope is "self", and the public receipt
        # carries the recipient.  Absent today.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        cleanse = _main_survival(combat)["cleanse"]
        assert cleanse["target"] == "main"
        assert cleanse["item"] == "Gangplank W"
        assert cleanse["decision"]["item"] == "Gangplank W"

    def test_w_activation_time_vs_cast_timeline(self):
        # P2-5 contract: the cleanse activation time pins to the W cast
        # timeline — in a timed fight the W cast starts at 0.25 (after
        # Q's 0.25 cast time) and the default activation lands with the
        # cast (the heal's landing time); in one_rotation at 0.0.  The
        # explicit option time overrides.  Absent today.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        cleanse = _main_survival(combat)["cleanse"]
        # The activation IS the W cast time (no explicit-time override —
        # there is no option; the cast is the activation).
        assert cleanse["activation_time"] == pytest.approx(0.25)
        # The W cast itself starts at 0.25 (the engine's cast timeline —
        # the activation IS that cast time; the S10 cast-timing pin
        # covers the engine row).

    def test_w_second_activation_fails_closed_use_spent(self):
        # P2-5 contract: the one-use latch (Slice 4) — a second W
        # activation in the same fight fails closed with the named
        # use_spent denial, the latch receipt shows the consumed use,
        # and the second activation truncates nothing further.  Absent
        # today.
        combat = _app_combat(
            {},
            {"Q": 5, "W": 0, "E": 5, "R": 0},
            duration=30.0,
        )
        survival = _main_survival(combat)
        assert survival["cleanse_denied"]  # the named use_spent receipts
        assert all(row["reason"] == "use_spent" for row in survival["cleanse_denied"])
        assert survival["cleanse_use"]["uses_after"] == 0

    def test_w_activation_without_control_consumes_use(self):
        # P2-5 contract: an activation with no control active still
        # consumes the one use (Slice 4 control_not_active semantics —
        # the heal fires, the cleanse receipts the denial).  Absent.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 0, "R": 0})
        survival = _main_survival(combat)
        assert survival["cleanse"]["decision"]["reason"] == "control_not_active"
        assert survival["cleanse"]["use_consumed"] is True
        assert survival["cleanse_use"]["uses_after"] == 0


# ---------------------------------------------------------------------------
# S5 — Crowd control + suppression gates
# ---------------------------------------------------------------------------


class TestCrowdControlAndSuppression:
    def test_kernel_self_scope_airborne_and_suppression_rules(self):
        # Kernel evidence (PASS): the Slice 4 kernel already implements
        # every W gate — an airborne interval is rejected with the named
        # excluded_control_kind reason (the displacement-override
        # boundary), a suppression interval blocks the self-cast with
        # caster_control_blocks_cleanse (use NOT consumed), and an
        # active stun is truncated at the activation.
        declaration = {
            "item": "Remove Scurvy",
            "active_name": "Remove Scurvy",
            "target_scope": "self",
            "excluded_control_kinds": ("airborne",),
            "cooldown_seconds": None,
            "cooldown_source_gap": True,
            "heal": None,
            "movement": None,
        }
        eligibility = CleanseEligibility(declaration=declaration)
        base = {
            "time": 1.5,
            "source_key": "Remove Scurvy",
            "sequence": 0,
            "event_id": "w:0",
            "target": "main",
            "holder": "main",
        }
        airborne = eligibility.decide(
            SimpleNamespace(
                **base,
                active_controls=[
                    {"kind": "airborne", "start": 1.0, "end": 2.5, "source": "R"}
                ],
            )
        )
        assert airborne.eligible is False
        assert airborne.reason == "excluded_control_kind"
        assert airborne.removed_controls == []
        assert airborne.rejected_controls[0]["reason"] == "excluded_control_kind"
        suppression = eligibility.decide(
            SimpleNamespace(
                **base,
                active_controls=[
                    {"kind": "suppression", "start": 1.0, "end": 3.0, "source": "R"}
                ],
            )
        )
        assert suppression.eligible is False
        assert suppression.reason == "caster_control_blocks_cleanse"
        assert suppression.use_consumed is False
        stun = eligibility.decide(
            SimpleNamespace(
                **base,
                active_controls=[
                    {"kind": "stun", "start": 1.0, "end": 3.0, "source": "E"}
                ],
            )
        )
        assert stun.eligible is True
        assert stun.removed_controls[0]["control_kind"] == "stun"
        assert stun.intervals_after == [
            {
                "control_kind": "stun",
                "source": "E",
                "start": pytest.approx(1.0),
                "end": pytest.approx(1.5),
            }
        ]

    def test_w_cleanse_truncates_active_control_at_activation(self):
        # P2-5 contract: the W cleanse truncates the ACTIVE control
        # interval at the activation (the Slice 4 truncate_intervals
        # contract) — the charm [0, 1.8] ends at 0.25, action_downtime
        # drops to 0.25, the receipt names the removed tail.  Absent.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        survival = _main_survival(combat)
        cleanse = survival["cleanse"]
        assert cleanse["decision"]["reason"] == ""
        assert cleanse["removed_controls"] == [
            {
                "control_kind": "immobilize",
                "source": "E",
                "start": pytest.approx(0.25),
                "end": pytest.approx(1.8),
                "reason": "",
            }
        ]
        assert survival["action_downtime"] == pytest.approx(0.25)
        assert survival["crowd_control_until"] == pytest.approx(0.25)
        assert survival["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "immobilize",
                "start": 0.0,
                "end": 0.25,
                "source": "E",
            }
        ]

    def test_w_cleanse_fires_while_caster_is_crowd_controlled(self):
        # P2-5 contract (the spell's defining property): the W activation
        # is NOT blocked by the caster's own crowd control (the QSS/
        # Mercurial castability precedent — a self cleanse is castable
        # while disabled), and the heal lands with it (the current
        # attacker_state_blocked gating of the authored heal must be
        # lifted for the activation).  Absent today: the heal is gated
        # and no cleanse exists.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        survival = _main_survival(combat)
        assert survival["cleanse"]["decision"]["reason"] == ""
        (heal,) = _main_heals(combat)
        assert heal.get("skipped_reason") is None
        assert heal["applied_amount"] > 0.0

    def test_w_control_landing_after_activation_untouched(self):
        # P2-5 contract: a control landing AFTER the activation is
        # untouched (a cleanse creates NO immunity).  Absent today.
        # Deterministic couple-walk pin: a control landing AFTER the
        # activation is untouched (a cleanse creates NO immunity) — the
        # later charm's full interval survives into the ledger.
        combatants = [
            _dummy_combatant("enemy", "enemy"),
            _dummy_combatant("main", "main"),
        ]
        result = simulate_survival(
            combatants,
            {
                "main": [
                    _control_packet(0.5, "immobilize", 1.8, source="E"),
                    _control_packet(2.0, "immobilize", 1.8, source="E"),
                ]
            },
            {},
            {
                "main": [
                    {
                        "time": 1.5,
                        "kind": "cleanse",
                        "amount": 1.0,
                        "attacker": "main",
                        "target": "main",
                        "source": "Gangplank W — Remove Scurvy",
                        "source_key": "Gangplank W",
                        "utility_kind": "cleanse",
                        "cleanse_item": "Gangplank W",
                        "sequence": 0,
                        "_event_id": "w:cleanse:0",
                    }
                ]
            },
            10.0,
        )
        main_state = result["main"]
        assert main_state["cleanse"]["decision"]["eligible"] is True
        # The first charm truncated at 1.5; the second (landing at 2.0)
        # keeps its FULL interval — no immunity.
        intervals = main_state["crowd_control_intervals"]
        assert len(intervals) == 2
        assert intervals[0]["end"] == pytest.approx(1.5)
        assert intervals[1]["start"] == pytest.approx(2.0)
        assert intervals[1]["end"] == pytest.approx(3.8)

    def test_w_suppression_fails_closed(self):
        # P2-5 contract: an active suppression at the activation fails
        # closed with the named caster_control_blocks_cleanse denial
        # (self-scope castability — the cleanse cannot be cast under
        # suppression), the interval is untouched and the use is NOT
        # consumed.  Absent today.
        combatants = [
            _dummy_combatant("enemy", "enemy"),
            _dummy_combatant("main", "main"),
        ]
        result = simulate_survival(
            combatants,
            {"main": [_control_packet(1.0, "suppression", 2.0, source="R")]},
            {},
            {
                "main": [
                    {
                        "time": 1.5,
                        "kind": "cleanse",
                        "amount": 0.0,
                        "attacker": "main",
                        "target": "main",
                        "source": "Remove Scurvy",
                        "source_key": "Remove Scurvy",
                        "utility_kind": "cleanse",
                        "sequence": 0,
                        "_event_id": "w:0",
                    }
                ]
            },
            10.0,
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["decision"]["reason"] == "caster_control_blocks_cleanse"
        assert cleanse["removed_controls"] == []
        assert result["main"]["action_downtime"] == pytest.approx(2.0)
        assert result["main"]["cleanse_use"]["uses_after"] == 1

    def test_w_a_pull_is_the_declared_displacement_carve_out(self):
        # F-9 correction to the P2-5 contract: ``pull`` is not
        # ``unknown_control`` (the verdict of a cleanse carrying its own kind
        # vocabulary).  It is an Airborne subtype, and Remove Scurvy's
        # declaration carves the displacement family out, so the interval
        # survives with the named excluded_control_kind denial instead.
        # A *misspelled* kind never reaches this layer at all (next test).
        combatants = [
            _dummy_combatant("enemy", "enemy"),
            _dummy_combatant("main", "main"),
        ]
        result = simulate_survival(
            combatants,
            {"main": [_control_packet(1.0, "pull", 2.0, source="E")]},
            {},
            {
                "main": [
                    {
                        "time": 1.5,
                        "kind": "cleanse",
                        "amount": 0.0,
                        "attacker": "main",
                        "target": "main",
                        "source": "Remove Scurvy",
                        "source_key": "Remove Scurvy",
                        "utility_kind": "cleanse",
                        "sequence": 0,
                        "_event_id": "w:0",
                    }
                ]
            },
            10.0,
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["decision"]["reason"] == "excluded_control_kind"
        assert cleanse["removed_controls"] == []
        assert result["main"]["crowd_control_intervals"][0]["end"] == pytest.approx(3.0)
        assert result["main"]["cleanse_use"]["uses_after"] == 0

    def test_w_a_kind_outside_the_vocabulary_is_refused_at_the_seam(self):
        # ``cc_kind`` is a closed vocabulary: a misspelling is a raise at
        # the timeline seam, before any cleanse decision exists, so it can
        # never author a no-op stun the W would then "fail to remove".
        combatants = [
            _dummy_combatant("enemy", "enemy"),
            _dummy_combatant("main", "main"),
        ]
        with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
            simulate_survival(
                combatants,
                {"main": [_control_packet(1.0, "dance", 2.0, source="E")]},
                {},
                {},
                10.0,
            )

    def test_w_airborne_displacement_override_named_boundary(self):
        # P2-5 contract: the airborne displacement-override note is a
        # NAMED boundary — an airborne interval at the activation is NOT
        # removed (the stun-under-airborne removal is not modeled as an
        # interval split), the declaration's excluded_control_kinds
        # contains "airborne", and the receipt rejects it with the named
        # excluded_control_kind reason.  Absent today.
        import src.calculator.champions.gangplank as gp_module

        rule = getattr(gp_module, "REMOVE_SCURVY_RULE", None)
        assert rule is not None, "typed W declaration absent"
        receipt = rule.public_receipt() if hasattr(rule, "public_receipt") else rule
        assert "airborne" in receipt["excluded_control_kinds"]
        combatants = [
            _dummy_combatant("enemy", "enemy"),
            _dummy_combatant("main", "main"),
        ]
        result = simulate_survival(
            combatants,
            {"main": [_control_packet(1.0, "airborne", 2.0, source="R")]},
            {},
            {
                "main": [
                    {
                        "time": 1.5,
                        "kind": "cleanse",
                        "amount": 0.0,
                        "attacker": "main",
                        "target": "main",
                        "source": "Remove Scurvy",
                        "source_key": "Remove Scurvy",
                        "utility_kind": "cleanse",
                        "sequence": 0,
                        "_event_id": "w:0",
                    }
                ]
            },
            10.0,
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["removed_controls"] == []
        assert cleanse["rejected_controls"][0]["control_kind"] == "airborne"
        assert cleanse["rejected_controls"][0]["reason"] == "excluded_control_kind"


# ---------------------------------------------------------------------------
# S6 — Interval truncation
# ---------------------------------------------------------------------------


class TestIntervalTruncation:
    def test_w_historical_downtime_remains_active_interval_ends(self):
        # P2-5 contract (brief contract #6): historical downtime before
        # the activation REMAINS counted; an active interval ENDS at the
        # activation.  Absent today.
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        cleanse = _main_survival(combat)["cleanse"]
        # The charm [0, 1.8] is active at 0.25: downtime_before is the
        # full 1.8, downtime_after only the pre-activation 0.25.
        assert cleanse["downtime_before"] == pytest.approx(1.8)
        assert cleanse["downtime_after"] == pytest.approx(0.25)

    def test_w_rides_slice4_truncate_intervals_kernel(self):
        # Kernel evidence (PASS): the exact truncation the W must ride
        # (the Slice 4 matrix's committed rule): historical intervals
        # kept, the active tail removed, a control starting at/after the
        # activation removed entirely by the pure function (the walk
        # never passes a control landing later — a cleanse creates no
        # immunity), unknown kinds never truncated.
        from src.calculator.cleanse_eligibility import truncate_intervals

        intervals = [
            {"kind": "stun", "start": 0.0, "end": 1.0, "source": "A"},  # historical
            {"kind": "stun", "start": 1.0, "end": 3.0, "source": "B"},  # active
            {"kind": "stun", "start": 1.5, "end": 2.0, "source": "C"},  # at activation
            {"kind": "stun", "start": 2.0, "end": 4.0, "source": "D"},  # after
            {"kind": "dance", "start": 0.0, "end": 9.0, "source": "E"},  # unknown
        ]
        kept, removed = truncate_intervals(intervals, 1.5, ("stun",))
        assert [row["source"] for row in kept] == ["A", "B", "E"]
        assert kept[1]["end"] == pytest.approx(1.5)
        assert [row["source"] for row in removed] == ["B", "C", "D"]
        assert removed[0]["start"] == pytest.approx(1.5)
        assert removed[1]["start"] == pytest.approx(1.5)
        assert removed[2]["source"] == "D"  # pure-function rule (see note)


# ---------------------------------------------------------------------------
# S7 — Named denials
# ---------------------------------------------------------------------------


class TestNamedDenials:
    def test_named_denial_vocabulary_pinned(self):
        # The named fail-closed denial vocabulary the W wiring must ride
        # (brief contract #7): the Slice 4 decision reasons plus the
        # unavailable-source KeyError and the score receipts.
        from src.calculator.cleanse_eligibility import CleanseDecision

        decision = CleanseDecision(eligible=False, reason="", item="")
        assert set(decision.public_receipt()) >= {
            "eligible",
            "reason",
            "item",
            "activation_time",
            "target",
            "removed_controls",
            "rejected_controls",
            "intervals_after",
            "use_consumed",
        }
        # P2-5: the champion source now RESOLVES (the declaration landed);
        # an unknown source still fails closed with the named KeyError.
        assert resolve_cleanse_item("Remove Scurvy") == "Gangplank W"
        assert resolve_cleanse_item("Gangplank W") == "Gangplank W"
        with pytest.raises(KeyError) as excinfo:
            resolve_cleanse_item("Bogus Cleanse")
        assert "Bogus Cleanse" in str(excinfo.value)
        # Score fail-closed receipts.
        assert (
            unrepresentable_template_receipt({"kind": "cleanse"})
            == "support_kind=cleanse"
        )
        assert (
            unrepresentable_template_receipt({"kind": "heal", "cleanse": True})
            == "support_cleanse"
        )
        assert (
            unrepresentable_template_receipt({"kind": "cleanse", "amount": 1.0})
            == "support_kind=cleanse"
        )
        assert (
            unrepresentable_template_receipt(
                {"kind": "heal", "amount": 100.0, "cleanse": True}
            )
            == "support_cleanse"
        )

    def test_w_denials_receipted_in_fight(self):
        # P2-5 contract: every denial surfaces as a named receipt in the
        # fight result — missing identity (identity-less activation),
        # invalid target (target_not_selected), unavailable source
        # (unresolved declaration), unsupported control/suppression
        # state (unknown_control / caster_control_blocks_cleanse), and
        # unsupported spatial or score behavior (the airborne boundary /
        # the score receipts).  Absent today (no W wiring).
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        survival = _main_survival(combat)
        assert survival["cleanse"]["decision"]["reason"] in {
            "target_not_selected",
            "not_armed",
            "unknown_control",
            "caster_control_blocks_cleanse",
            "control_not_active",
            "excluded_control_kind",
            "",
        }
        assert "cleanse_denied" in survival or "cleanse_use" in survival


# ---------------------------------------------------------------------------
# S8 — Score fail-closed behavior
# ---------------------------------------------------------------------------


class TestScoreFailClosed:
    def test_score_gate_names_fail_closed_receipts(self):
        # PASS: the compiled score path ALREADY fails closed on every W
        # authoring shape — a cleanse-kind template (support_kind=cleanse)
        # and a heal packet carrying the cleanse marker (support_cleanse)
        # are unrepresentable; a plain heal stays representable.  The
        # P2-5 wiring must route the W through this gate (never silently
        # re-price the heal as a plain heal or drop the cleanse).
        assert (
            unrepresentable_template_receipt({"kind": "cleanse"})
            == "support_kind=cleanse"
        )
        assert (
            unrepresentable_template_receipt(
                {"kind": "heal", "amount": 100.0, "cleanse": True}
            )
            == "support_cleanse"
        )
        assert (
            unrepresentable_template_receipt({"kind": "movement"})
            == "support_kind=movement"
        )
        assert (
            unrepresentable_template_receipt({"kind": "heal", "amount": 100.0}) is None
        )

    def test_w_score_only_never_silently_reprices(self):
        # P2-5 contract (the completion rule): the score adapter cannot
        # model the champion cleanse (interval truncation), so the W
        # cleanse packet fails closed with the NAMED receipt
        # (support_kind=cleanse) and the fight is priced by the receipt
        # walk — never a silent re-priced plain heal, never a silent
        # drop.
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": "Gangplank W",
            "source_key": "Gangplank W",
            "utility_kind": "cleanse",
            "source": "Gangplank W — Remove Scurvy",
            "time": 0.25,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:W:0",
        }
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"
        # The receipt walk prices the fight (the app-level couple payload
        # shows the full cleanse decision).
        combat = _app_combat({}, {"Q": 5, "W": 0, "E": 5, "R": 0})
        assert _main_survival(combat)["cleanse"]["decision"]["eligible"] is True


# ---------------------------------------------------------------------------
# S9 — Mode parity
# ---------------------------------------------------------------------------


class TestModeParity:
    def test_w_surface_byte_identical_under_score_only_today(self):
        # PASS today (no option): the W surface — breakdown row, mana
        # ledger, spent/remaining, cast timeline — is byte-identical
        # between the full walk and the compiled score path in both fight
        # modes.  The existing options never change the W row.
        for option in ({}, {"p_procs": 2}, {"r_fire_at_will": True}):
            for one_rotation in (True, False):
                full = _fight(option, one_rotation=one_rotation)
                scored = _fight(option, one_rotation=one_rotation, score_only=True)
                assert full["breakdown"]["W"] == scored["breakdown"]["W"]
                assert full["resource_spent"] == scored["resource_spent"]
                assert full["resource_remaining"] == scored["resource_remaining"]
                assert full["resource_ledger"] == scored["resource_ledger"]
                # The score path's cast rows carry only the shared core
                # fields (the K'Sante matrix's parity convention).
                shared = ("time", "slot", "name", "ordinal", "resource_cost")
                for full_row, scored_row in zip(
                    full["cast_timeline"], scored["cast_timeline"], strict=False
                ):
                    assert {k: full_row[k] for k in shared} == {
                        k: scored_row[k] for k in shared
                    }

    def test_w_mode_parity_contract_with_option(self):
        # P2-5 contract: the engine surface (W row, mana, totals) is
        # byte-identical full vs score_only — the W stays OUT of outgoing
        # damage in both modes — and the couple score gate names the
        # fail-closed receipt for the cleanse packet (the completion
        # rule's pinned divergence).
        full = _fight({}, one_rotation=True)
        scored = _fight({}, one_rotation=True, score_only=True)
        assert full["breakdown"]["W"] == scored["breakdown"]["W"]
        assert full["total_damage"] == scored["total_damage"]
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": "Gangplank W",
            "source_key": "Gangplank W",
            "utility_kind": "cleanse",
            "source": "Gangplank W — Remove Scurvy",
            "time": 0.0,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:W:0",
        }
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"


# ---------------------------------------------------------------------------
# S10 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_w_mana_spend_pinned(self):
        # Pinned actual (brief contract #10's question): the W cast DOES
        # spend mana today — 60/70/80/90/100 by rank, receipted as the
        # "ability W cast" ledger spend; the one-rotation ledger books it
        # against the opening pool.
        for rank, cost in zip(range(1, 6), _W_COST, strict=False):
            _, abilities = _parse(ranks={**_RANKS, "W": rank})
            assert abilities["W"]["cooldown"] == pytest.approx(_W_COOLDOWN[rank - 1])
            assert abilities["W"]["resource_cost"] == pytest.approx(cost)
        result = _fight({}, one_rotation=True)
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        spends = {
            row["source"]: row
            for row in ledger["receipts"]
            if row["operation"] == "spend"
        }
        assert spends["ability W cast"]["amount"] == pytest.approx(100.0)
        assert spends["ability W cast"]["detail"] == {"slot": "W", "ordinal": 1}
        assert result["resource_spent"] == pytest.approx(30.0 + 100.0 + 1.0 + 100.0)

    def test_w_cast_timing_unchanged(self):
        # Timed fight: the W cast starts at 0.25 (after Q's 0.25 cast
        # time) with cast_time 0.25; one_rotation casts land at 0.0.
        result = _fight({}, duration=10.0)
        (w_cast,) = [c for c in result["cast_timeline"] if c["slot"] == "W"]
        assert w_cast["time"] == pytest.approx(0.25)
        assert w_cast["resource_cost"] == pytest.approx(100.0)
        one = _fight({}, one_rotation=True)
        (w_one,) = [c for c in one["cast_timeline"] if c["slot"] == "W"]
        assert w_one["time"] == pytest.approx(0.0)

    def test_p_q_e_r_unchanged(self):
        # P/Q/E/R damage surfaces stay unchanged (brief contract #10):
        # the typed extractions at rank 5 and the fight rows.
        _, abilities = _parse()
        assert abilities["passive"]["name"] == "Trial by Fire"
        assert abilities["passive"]["total_raw"] == 0.0
        q = _GANPLANK_DATA["abilities"]["Q"][0]
        q_value = extract_named(q, "Physical Damage", 5, _stats())
        assert abilities["Q"]["total_raw"] == pytest.approx(q_value)
        assert abilities["Q"]["parts"][0].damage_type == "physical"
        e = _GANPLANK_DATA["abilities"]["E"][0]
        e_value = extract_named(e, "Bonus Champion Damage", 5, _stats())
        assert abilities["E"]["total_raw"] == pytest.approx(e_value)
        r = _GANPLANK_DATA["abilities"]["R"][0]
        r_value = extract_named(r, "Magic Damage Per Wave", 3, _stats())
        assert abilities["R"]["total_raw"] == pytest.approx(r_value * 12)
        result = _fight({}, one_rotation=True)
        assert result["breakdown"]["Q"]["total_damage"] > 0.0
        assert result["breakdown"]["R"]["total_damage"] > 0.0
        assert result["breakdown"]["E"]["total_damage"] > 0.0
        assert result["breakdown"]["W"]["total_damage"] == 0.0

    def test_r_options_branching_unchanged(self):
        # The existing R options keep their branches (Fire at Will 18
        # waves, Death's Daughter true damage).
        _, plain = _parse()
        _, upgraded = _parse({"r_fire_at_will": True, "r_deaths_daughter": True})
        r = _GANPLANK_DATA["abilities"]["R"][0]
        per_wave = extract_named(r, "Magic Damage Per Wave", 3, _stats())
        true_dd = extract_named(r, "True Damage with Death's Daughter", 3, _stats())
        assert upgraded["R"]["total_raw"] == pytest.approx(per_wave * 18 + true_dd)
        assert plain["R"]["total_raw"] == pytest.approx(per_wave * 12)
        assert "Fire at Will=on" in upgraded["R"]["detail"]
        assert "Death's Daughter=on" in upgraded["R"]["detail"]

    def test_w_does_not_touch_item_cleanse_surface(self):
        # The Slice 4 ITEM cleanses are an unchanged boundary (brief
        # contract #10): the item declarations and the one-use latch
        # stay the three declared items; Gangplank's W adds a champion
        # source without disturbing them.
        from src.calculator.cleanse_eligibility import ITEM_CLEANSE_DECLARATIONS

        assert set(ITEM_CLEANSE_DECLARATIONS) == {
            "Mikael's Blessing",
            "Quicksilver Sash",
            "Mercurial Scimitar",
        }
        for item in ITEM_CLEANSE_DECLARATIONS:
            assert resolve_cleanse_item(item) == item


# ---------------------------------------------------------------------------
# S11 — Regression surface (run list)
# ---------------------------------------------------------------------------
#
#
# The broader regression surface (every test that touches gangplank /
# scurvy / cleanse / cleanse_eligibility, per the brief contract #11):
#   tests/test_cleanse_eligibility.py tests/test_cleanse_eligibility_kernel.py
#   tests/test_cleanse_eligibility_consumers.py tests/test_e1_healing_b3.py
#   tests/test_heal_ledger_phase2.py tests/test_issue_143.py
#   tests/test_crowd_control_immunity.py tests/test_survival_kernel.py
#   tests/test_guardian_angel_resurrection.py tests/test_app.py
