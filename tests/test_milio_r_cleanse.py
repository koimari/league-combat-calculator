"""P2 Slice 7 — Milio R (Breath of Life) champion cleanse (test-matrix
owner: RLM-2 C).

Focused TDD matrix for Milio's R (Breath of Life) champion cleanse.
CURRENT RUNTIME FACTS (verified before pinning):

- Milio is a PACKET module (src/calculator/champions/milio.py,
  PACKET_SHA256 fce2851d...): Q is modeled; W/R heal allies via the
  E8d ally-support fan-out.  The module's R parse receipt: name
  "Breath of Life", rank 3, MANA cost 100, cast_time None (the cached
  castTime is "none"), total_raw 0.0 and NO parts — the R is
  non-damaging; the cooldown row is NOT published by the packet module
  (parse cooldown is 0.0 today — the typed declaration must receipt it).
- The R cached wording (data/champions.json "Milio", R[0]):
  effects[0] "Active: Milio explodes in soothing flames, healing and
  cleansing himself and nearby allied champions of non-airborne crowd
  control, and granting them 65% tenacity for 3 seconds." (Heal
  leveling 150/250/350 + 50% AP; cost 100 flat; cooldown 160/145/130
  affectedByCdr; targeting Auto; affects "Self, Allies"; resource
  MANA; castTime "none"; effectRadius 700).  effects[1] "Milio cannot
  cast his other abilities for 0.75 seconds after Breath of Life's
  activation. Breath of Life cannot be used while affected by
  cast-inhibiting crowd control."  The ASSUMPTIONS say "the 65%
  tenacity and cleanse are utility state".
- THE R HEAL IS ALREADY AUTHORED (healing.py's Milio branch, the
  E1-rule owner; the slot is in the participant timeline's fan-out):
  one champion_ability heal per R cast at the CAST START time with the
  live amount = 150/250/350 + 50% AP, target_scope
  self_and_all_teammates, actor_wide; the self copy lands in the main's
  healing ledger ("milio:r:{cast_index}") and the participant timeline
  fans the SAME formula out to every selected teammate as support heal
  templates (kind heal, target_scope self_and_all_teammates,
  target_policy self_and_all_selected_teammates, event_id
  "{applied_self_id}:ally:{i}", source_event_id = the self copy's
  applied id) — one formula prices every recipient.
- The R heal rides the survival walk's attacker-state gate: while the
  CASTER is crowd-controlled the heal (self copy AND ally copies) is
  skipped with attacker_state_blocked and never lands (probe-pinned
  with enemy Ahri charming main at t=0: R heal at 0.25 -> skipped on
  main and ally:Jinx).  This is the OPPOSITE of the Slice 5/6
  castability carve-out (GP W heal / Rengar empowered-W heal carry
  cast_while_disabled); Milio's R "cannot be used while affected by
  cast-inhibiting crowd control", so a CC'd caster authors NO effect.
- The engine cast_timeline is the activation clock: one_rotation casts
  Q/W/E/R all at 0.0; timed rank-3 casts Q@0.0, W@0.0, E@0.25, R@0.25
  (R cost 100).  RANK 0 IS NOT A CAST GATE today: the engine books the
  R cast at every rank (packet modules rotate every SLOT) and the heal
  fires with the rank-clamped value (extract_named rank 0 reads the
  LAST row value 350) — the "R rank 0 -> no cast" contract is a
  completion fix (xfailed below).
- The Slice 4/5/6 champion-cleanse kernel (CHAMPION_CLEANSE_DECLARATIONS
  — Gangplank W + Rengar W — + the per-cast packet authoring in
  participant_timeline._support_effect_templates AFTER the heal fan-out
  + _apply_cleanse + the per-fight one-use latch keyed by the
  declaration item on the CASTER + the cleanse/cleanse_use/
  cleanse_denied receipts) does NOT wire Milio today:
  resolve_cleanse_item("Milio R") FAILS CLOSED with a KeyError naming
  the source; the app-level fight carries NO cleanse keys anywhere and
  utility_outcomes cleanse event_count is 0.  The kernel's decide()
  knows only scopes "self" and "explicit_selected_ally" (no
  self_and_all_teammates), the self-scope castability block is only
  CAST_BLOCKING_CONTROL_KINDS = {"suppression"} (the QSS/Mercurial
  cannotBeSuppressed rule), and each packet's decision consumes the
  one use (a multi-recipient cast needs a shared-use decision).
- Game-file evidence (data/bin/characters/milio.bin.json MilioR):
  HealBase DataValues [50,150,250,350,...] (ranks 1..3 = 150/250/350),
  mSpellCalculations HealCalc = HealBase + StatByCoefficient 0.5 (50%
  AP), cooldownTime [160,160,145,130,...] (ranks 1..3 = 160/145/130),
  mana 100, mCastTime 0.713 (the game cast time — the wiki cached
  castTime is "none" and the engine books no cast time), mTargetingType
  SelfAoe, castRange 700, TenacityDuration 3.0, TenacityAmount 0.65,
  and NO canCastWhileDisabled / cannotBeSuppressed flags (the QSS/
  Mercurial flag pair is ABSENT — consistent with the cast-inhibiting
  gate, the OPPOSITE of GP/Rengar).

The coordinator's completion (P2-7) will (most likely) add the Milio R
declaration + authoring: self AND all selected teammates scope (the
same roster the heal fans out to), the non-airborne exclusion, the
CASTABILITY GATE (the R cannot be used while the CASTER is
crowd-controlled — the Mikael's-style gated path, use NOT consumed,
the OPPOSITE of the GP/Rengar utility-before-gate dispatch), the heal
(E8d fan-out) + cleanse separate, the per-fight one-use latch shared
by one cast's recipients, the cooldown receipted but never enforced,
and the score fails closed (support_kind=cleanse).  This matrix pins
the CONTRACT; genuinely-absent mechanics are pytest.mark.xfail
(non-strict) with reason "awaiting P2-7 ..." — the completion removes
the markers.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (cached R rows; the cleanse +
      castability wording; the game file; the module parse receipt;
      the R heal public receipt in parse + fight result; the source
      receipts; the absent typed R declaration xfailed).
  S2  No R (R rank 0; the option set unchanged; the rank-0 cast-gate
      contract xfailed — the engine casts R at every rank today).
  S3  R timing (engine cast_timeline one_rotation 0.0 / timed 0.25;
      the heal lands at the cast time; the activation-time == cast
      time contract xfailed).
  S4  Heal + cleanse separate (the E8d ally heal receipts; the heal
      fires with no control active; the cleanse receipts contract
      xfailed).
  S5  Self + all selected teammates scope (the heal fan-out roster;
      per-recipient decisions xfailed; the kernel self-scope
      target_not_selected evidence).
  S6  Exact control exclusions (non-airborne wording; the kernel
      excluded_control_kind evidence; the wired Milio exclusion
      xfailed; the displacement-family boundary).
  S7  Castability while crowd controlled (the heal attacker-gate pin —
      the OPPOSITE of the GP/Rengar carve-out; suppression kernel
      evidence; the wired named-denial contract xfailed).
  S8  One-use and cooldown boundaries (the kernel latch evidence; the
      shared-per-cast latch + cooldown receipt xfailed; the heals fire
      per cast).
  S9  Same-time ordering (the kernel order — heal fan-out templates
      before the champion cleanse block; same-time heal + cleanse
      kernel evidence).
  S10 Repeated casts (kernel use_spent evidence; the Milio second-cast
      contract xfailed).
  S11 Truncation (the truncate_intervals contract; per-recipient
      truncation xfailed; historical downtime + later controls).
  S12 Missing identity + rows (the unavailable-source KeyError pinned;
      the _require_row fail-loud precedent).
  S13 Score fail-closed (the generic gate receipts PASS; never a
      silent re-price).
  S14 Full vs score parity (byte-identical R surface today; the named
      cleanse divergence xfailed).
  S15 Unchanged boundaries (W/E ally support, Q damage, R out of
      damage, the GP/Rengar + item cleanse tables, the options meta).
  S16 Regression surface (the mandated sanity run list, footer).

Expected heal values are recomputed from data/champions.json leveling
rows — no literal damage constants.  The R heal/cost/cooldown arrays
ARE the values under test (the typed declaration must publish them),
so they appear as pinned cache rows (the K'Sante / Gangplank / Rengar
matrix precedent).  The declaration item key below is a pinned
CANDIDATE ("Milio R"); the coordinator's final spelling is a contract
ambiguity reported to the parent.
"""

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import app as app_module
from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.slotlib import extract_named
from src.calculator.cleanse_eligibility import (
    CHAMPION_CLEANSE_DECLARATIONS,
    ITEM_CLEANSE_DECLARATIONS,
    CleanseDecision,
    CleanseEligibility,
    compiled_support_receipt,
    resolve_cleanse_item,
    truncate_intervals,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.healing import derive_self_healing
from src.calculator.participant_timeline import (
    Combatant,
    _simulate_survival as _simulate_survival_walk,
)
from src.calculator.survival.compile import unrepresentable_template_receipt


# MERGE: ``_simulate_survival`` returns the frozen ``WalkResult`` now -- one
# walk handed to five views -- so a caller that wants the published rows
# projects it through the survival view, exactly as the composition does.
def _simulate_survival(combatants, *args, **kwargs):
    combatant_list = list(combatants)
    return _survival_view(
        _roster_program(combatant_list),
        _simulate_survival_walk(combatant_list, *args, **kwargs),
    )


_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_MILIO_DATA = _CHAMPION_DATA["Milio"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P2-7 coordinator wires the typed R declaration + the cleanse
# packet authoring; genuinely-absent mechanics are xfailed with this
# reason (never strict — the completion removes the markers).
_AWAIT = "awaiting P2-7 wiring"

# The cached R rows the typed declaration must publish (values under
# test — pinned as cache evidence, never literal damage constants).
_R_HEAL_FLAT = [150, 250, 350]
_R_AP_PERCENT = 50
_R_COST = [100, 100, 100]
_R_COOLDOWN = [160, 145, 130]
_R_CAST_TIME = None  # cached castTime "none" — the engine books no cast time

# Pinned CANDIDATE declaration key for the coordinator (the GP/Rengar
# mirror): the packet source_key / cleanse_item / latch key.
_R_CLEANSE_ITEM = "Milio R"


def _stats(ap: float = 100.0) -> dict:
    return {
        "attack_damage": 100.0,
        "ability_power": ap,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 40.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 1100.0,
        "resource_regen_per_second": 0.0,
        "level": _LEVEL,
        "health": 2000.0,
        "max_health": 2000.0,
    }


def _parse(option: dict | None = None, *, ranks: dict | None = None):
    stats = _stats()
    abilities = parse_champion_abilities(
        get_champion("Milio"),
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
    duration: float = 30.0,
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


@contextlib.contextmanager
def _testing_client():
    """A flask test client with TESTING enabled, restored afterwards.

    The flask app config is process-global: test_app.py's rate-limit tests
    rely on ``TESTING`` being False (the limiter is bypassed under
    TESTING), so this file must never leave the flag set.
    """
    previous = app_module.app.config.get("TESTING", False)
    app_module.app.config["TESTING"] = True
    try:
        yield app_module.app.test_client()
    finally:
        app_module.app.config["TESTING"] = previous


def _app_combat(
    *,
    enemy: str = "Garen",
    duration: float = 6.0,
    ranks: dict | None = None,
    allies: list[dict] | None = None,
) -> dict:
    """The app-level combat payload (full pipeline + survival walk).

    The roster path (allies key, ally_effects_enabled) is required for the
    R fan-out to see selected teammates.  Garen (no crowd control) keeps
    the heal rows observable; Ahri (immobilize charm at t=0 on main AND
    every selected ally) is used for the crowd-control gates.
    """
    with _testing_client() as client:
        response = client.post(
            "/api/calculate",
            json={
                "champion": "Milio",
                "level": _LEVEL,
                "items": [],
                "role": "support",
                "ability_ranks": ranks or _RANKS,
                "fight_mode": "time_based",
                "fight_duration": duration,
                "include_auto_attacks": False,
                "target_health": _TARGET_MAX_HP,
                "target_armor": 50,
                "target_mr": 40,
                "champion_options": {},
                "allies": allies
                or [
                    {
                        "champion": "Jinx",
                        "level": _LEVEL,
                        "items": [],
                        "ally_effects_enabled": True,
                    }
                ],
                "enemies": [
                    {
                        "champion": enemy,
                        "level": _LEVEL,
                        "items": [],
                        "ability_ranks": _RANKS,
                    }
                ],
            },
        )
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _survival(combat: dict, participant_id: str = "main") -> dict:
    return next(
        row["survival"]
        for row in combat["participants"]
        if row["participant_id"] == participant_id
    )


def _main_heals(combat: dict) -> list[dict]:
    """The self R-heal receipts (the E1-rule self copies)."""
    return [
        e
        for e in combat.get("healing_events", [])
        if e.get("attacker") == "main" and e.get("source") == "Breath of Life"
    ]


def _breath_support(combat: dict) -> list[dict]:
    """The fan-out copies (support heal templates for selected allies)."""
    return [
        e
        for e in combat.get("support_events", [])
        if e.get("attacker") == "main" and e.get("source") == "Breath of Life"
    ]


def _cleanse_event_count(combat: dict) -> int:
    return combat["utility_outcomes"]["participants"]["main"]["cleanse"]["event_count"]


def _r_ability() -> dict:
    return _MILIO_DATA["abilities"]["R"][0]


def _r_flat(rank: int, ap: float) -> float:
    """Recompute the R heal through the typed path: flat + 50% AP."""
    return extract_named(_r_ability(), "Heal", rank, {"ability_power": ap})


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
        stats={"health": health, "max_health": health},
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


def _heal_event(time: float, amount: float) -> dict:
    # The harness heals are the pair's SELF copies (the runtime's fan-out
    # lives in participant_timeline — a target_scope here would make the
    # walk treat the event as an unresolved fan-out template).
    return {
        "time": time,
        "amount": amount,
        "source": "Breath of Life",
        "kind": "champion_ability",
        "attacker": "main",
        "_event_id": f"main:heal:r:{time}",
    }


def _milio_cleanse_packet(
    time: float,
    index: int,
    *,
    target: str = "main",
    attacker: str = "main",
    group: str = "milio:r:cast0",
) -> dict:
    """The P2-7 packet shape (the GP/Rengar authoring mirror): one
    cleanse packet per R-cast recipient at the cast time, riding the
    Slice 4 kernel with the Milio R source.  The ``group`` is the
    per-cast one-use latch key — every recipient of ONE cast shares it
    (the runtime authoring rides the E8d heal fan-out's group)."""
    return {
        "time": time,
        "kind": "cleanse",
        "amount": 1.0,
        "cleanse_item": _R_CLEANSE_ITEM,
        "source_key": _R_CLEANSE_ITEM,
        "utility_kind": "cleanse",
        "source": "Milio R — Breath of Life",
        "attacker": attacker,
        "target": target,
        "cleanse_group": group,
        "sequence": 0,
        "_event_id": f"milio:cleanse:R:{index}",
    }


def _damage_packet(time: float, amount: float) -> dict:
    """One incoming damage packet (the kernel harness heal-application
    requires at least one incoming event)."""
    return {
        "time": time,
        "damage": amount,
        "raw_damage": amount,
        "damage_type": "magic",
        "attacker": "enemy",
        "target": "main",
        "source_key": "Q",
        "source": "Q",
        "is_ability": True,
        "kind": "damage",
        "sequence": 0,
        "_event_id": f"dmg-{time}",
    }


def _kernel_survival(
    controls: list[dict] | None = None,
    heals: list[dict] | None = None,
    cleanses: list[dict] | None = None,
    *,
    duration: float = 10.0,
    main_health: float = 3000.0,
) -> dict:
    """Kernel-level survival run (the Slice 4/5/6 evidence path)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("main", "main", health=main_health),
    ]
    return _simulate_survival(
        combatants,
        {"main": list(controls or [])},
        {"main": list(heals or [])},
        {"main": list(cleanses or [])},
        duration,
        annotate=False,
    )


def _game_file() -> dict:
    path = Path("data/bin/characters/milio.bin.json")
    if not path.exists():
        pytest.skip("local Milio game-file evidence is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_r_rows_pinned_in_cache(self):
        # The R "Heal" leveling row is 150/250/350 flat + 50% AP; cost
        # 100 flat; cooldown 160/145/130 affected by CDR; castTime
        # "none"; effectRadius 700; Self, Allies / Auto / MANA; no
        # damage type.  These are the values the P2-7 typed declaration
        # must publish (the brief's contract #1).
        heal = next(
            leveling
            for effect in _r_ability().get("effects", [])
            for leveling in effect.get("leveling", [])
            if leveling.get("attribute") == "Heal"
        )
        assert heal["modifiers"][0]["values"] == _R_HEAL_FLAT
        assert heal["modifiers"][0]["units"] == ["", "", ""]
        assert heal["modifiers"][1]["values"] == [_R_AP_PERCENT] * 3
        assert heal["modifiers"][1]["units"] == ["% AP"] * 3
        r = _r_ability()
        assert r["cost"]["modifiers"][0]["values"] == _R_COST
        assert r["cooldown"]["modifiers"][0]["values"] == _R_COOLDOWN
        assert r["cooldown"]["affectedByCdr"] is True
        assert r["castTime"] == "none"
        assert r["effectRadius"] == "700"
        assert r["targeting"] == "Auto"
        assert r["affects"] == "Self, Allies"
        assert r["resource"] == "MANA"
        assert r["damageType"] is None

    def test_r_cleanse_and_castability_wording_pinned(self):
        # The cleanse + castability wording (the brief's contract #1):
        # effects[0] carries the non-airborne cleanse + the 65% tenacity
        # grant; effects[1] carries the cast-inhibiting gate (the
        # "cannot be used" wording) plus the 0.75 s self-lock note.
        effects = _r_ability()["effects"]
        description = effects[0]["description"]
        assert "healing and cleansing himself and nearby allied champions" in (
            description
        )
        assert "non- airborne crowd control" in description
        assert "65% tenacity for 3 seconds" in description
        gate = effects[1]["description"]
        assert "Breath of Life cannot be used while affected by" in gate
        assert "cast-inhibiting crowd control" in gate
        assert "0.75 seconds after Breath of Life's activation" in gate

    def test_r_game_file_evidence(self):
        # Community Dragon evidence (the brief's "game file if present"):
        # HealBase 150/250/350 at ranks 1..3, HealCalc = HealBase + 0.5
        # coefficient (50% AP), cooldownTime 160/145/130 at ranks 1..3,
        # mana 100, mCastTime 0.713 (the game's real cast time — the
        # wiki cached castTime "none" is what the engine books), SelfAoe
        # targeting with castRange 700, TenacityDuration 3.0 and
        # TenacityAmount 0.65, and NO canCastWhileDisabled /
        # cannotBeSuppressed flags (the QSS/Mercurial flag pair is
        # ABSENT — the cast-inhibiting gate is the OPPOSITE of the
        # GP/Rengar declarations).
        game = _game_file()
        spell = game["Characters/Milio/Spells/MilioRAbility/MilioR"]["mSpell"]
        data = {d["name"]: d["values"] for d in spell["DataValues"]}
        assert data["HealBase"][1:4] == [150.0, 250.0, 350.0]
        assert data["TenacityDuration"][0] == pytest.approx(3.0)
        assert data["TenacityAmount"][0] == pytest.approx(0.65)
        calculations = spell["mSpellCalculations"]["HealCalc"]
        parts = calculations["mFormulaParts"]
        assert parts[0]["mDataValue"] == "HealBase"
        assert parts[1]["mCoefficient"] == pytest.approx(0.5)
        assert spell["cooldownTime"][1:4] == [160.0, 145.0, 130.0]
        assert spell["mana"][0] == pytest.approx(100.0)
        assert spell["mCastTime"] == pytest.approx(0.713, abs=1e-3)
        assert spell["mTargetingTypeData"]["__type"] == "SelfAoe"
        assert spell["castRange"][0] == pytest.approx(700.0)
        assert spell.get("canCastWhileDisabled") is None
        assert spell.get("cannotBeSuppressed") is None

    def test_r_public_receipt_present_in_parse(self):
        # The R public receipt at parse level (the packet module's
        # no_damage entry): name, rank, MANA cost 100, cast_time None,
        # zero total and no parts — the R is out of damage.  The parse
        # cooldown is 0.0 today (the packet module does not publish the
        # cooldown row — the P2-7 declaration must receipt it).
        _, abilities = _parse()
        r = abilities["R"]
        assert r["name"] == "Breath of Life"
        assert r["rank"] == 3
        assert r["resource_type"] == "MANA"
        assert r["resource_cost"] == pytest.approx(100.0)
        # The packet module emits NO cast_time key (the cached castTime
        # is "none" — the engine books no cast time).
        assert "cast_time" not in r
        assert r["total_raw"] == 0.0
        assert r["parts"] == ()
        assert "no enemy-damage formula" in r["detail"]

    def test_r_heal_values_recomputed(self):
        # Recompute through the module's typed path: extract_named
        # resolves flat + 50% AP at every rank (rank 0 clamps to the
        # LAST row value 350 — the pinned packet-module clamp the
        # completion's rank gate must supersede).
        for rank, flat in zip(range(1, 4), _R_HEAL_FLAT):
            assert _r_flat(rank, 100.0) == pytest.approx(flat + _R_AP_PERCENT)
            assert _r_flat(rank, 0.0) == pytest.approx(flat)
        assert _r_flat(0, 100.0) == pytest.approx(350.0 + _R_AP_PERCENT)

    def test_r_heal_receipt_authored_by_e1_rule(self):
        # The heal IS already authored (the E1-rule owner — the brief's
        # contract #4 "heal + cleanse separate"): one champion_ability
        # heal per R cast at the cast time with the live formula and the
        # self_and_all_teammates scope.  No R cast -> no heal event.
        heals = derive_self_healing(
            get_champion("Milio"),
            {"level": 18, "health": 2000.0, "ability_power": 100.0},
            {"R": {"rank": 3}},
            [],
            [{"slot": "R", "time": 0.25}],
            6.0,
        )
        assert len(heals) == 1
        heal = heals[0]
        assert heal["time"] == pytest.approx(0.25)
        assert heal["source"] == "Breath of Life"
        assert heal["kind"] == "champion_ability"
        assert heal["actor_wide"] is True
        assert heal["target_scope"] == "self_and_all_teammates"
        assert heal["amount"] == pytest.approx(400.0)  # 350 + 50% AP
        assert heal["_event_id"] == "milio:r:0"
        # Two R casts -> two heal events at the cast times.
        heals2 = derive_self_healing(
            get_champion("Milio"),
            {"level": 18, "health": 2000.0, "ability_power": 100.0},
            {"R": {"rank": 3}},
            [],
            [{"slot": "R", "time": 0.25}, {"slot": "R", "time": 130.25}],
            200.0,
        )
        assert [h["time"] for h in heals2] == [0.25, 130.25]

    def test_r_heal_receipt_in_fight_result(self):
        # The heal's public receipt in the fight result (the brief's
        # contract #1): the self copy lands in healing_events at the R
        # cast time 0.25 with the sourced rank-3 amount (AP 0 -> 350)
        # and the fan-out copy lands as a support heal template on the
        # selected ally at the same time with the same amount.
        combat = _app_combat()
        (self_heal,) = _main_heals(combat)
        assert self_heal["time"] == pytest.approx(0.25)
        assert self_heal["attacker"] == "main"
        assert self_heal["raw_amount"] == pytest.approx(350.0)
        assert self_heal["applied_amount"] > 0.0
        (ally_heal,) = _breath_support(combat)
        assert ally_heal["time"] == pytest.approx(0.25)
        assert ally_heal["target"] == "ally:Jinx"
        assert ally_heal["kind"] == "heal"
        assert ally_heal["raw_amount"] == pytest.approx(350.0)
        assert ally_heal["target_scope"] == "self_and_all_teammates"
        assert ally_heal["target_policy"] == "self_and_all_selected_teammates"
        assert ally_heal["event_id"].endswith(":ally:1")
        assert ally_heal["source_event_id"] == self_heal["event_id"]

    def test_r_source_receipts_pin_wiki_revisions(self):
        # Source receipts pin the wiki revisions the cached rows came from.
        sources = {
            row["label"]: row for row in get_champion_options_meta("Milio")["sources"]
        }
        assert sources["Milio parent entry"]["url"].endswith("/en-us/Milio")
        assert sources["Milio parent entry"]["revision_id"] == 3892686
        assert sources["Milio R ability entry"]["url"].endswith(
            "/en-us/Template:Data_Milio/R"
        )
        assert sources["Milio R ability entry"]["revision_id"] == 3535281

    def test_r_typed_declaration_publishes_cleanse_contract(self):
        # P2-7 contract: the champion-cleanse declaration for Milio R
        # (the GP/Rengar precedent) publishes the non-airborne cleanse —
        # self_and_all_teammates scope, the castability gate (blocked
        # while the caster is crowd-controlled — NOT the QSS/Mercurial
        # flag pair), the sourced wording, the cooldown row receipted
        # but never enforced, the heal left to the separate E1 fan-out
        # (heal None) — with provenance.  Absent today (only Gangplank W
        # and Rengar W are declared).
        rule = CHAMPION_CLEANSE_DECLARATIONS.get(_R_CLEANSE_ITEM)
        assert rule is not None, "Milio R cleanse declaration absent"
        assert rule["active_name"] == "Breath of Life"
        assert rule["target_scope"] == "self_and_all_teammates"
        assert rule["heal"] is None
        assert rule["cooldown_seconds"] == _R_COOLDOWN
        assert rule["cooldown_source_gap"] is False
        assert "airborne" in rule["excluded_control_kinds"]
        assert any(
            "non-airborne crowd control" in str(receipt.get("wording", ""))
            for receipt in rule["source_receipts"]
        )
        assert any(
            "cast-inhibiting crowd control" in str(receipt.get("wording", ""))
            for receipt in rule["source_receipts"]
        )


# ---------------------------------------------------------------------------
# S2 — No R
# ---------------------------------------------------------------------------


class TestNoR:
    def test_r_rank0_parse_and_option_set_unchanged(self):
        # R rank 0 -> the parse receipt ranks 0 and the options surface is
        # unchanged: the cleanse rides the R cast and adds NO user option.
        # Milio's one declared option belongs to P (Fired Up! proc count),
        # so what this pins is that R contributes nothing to it — the same
        # set at rank 0 and at rank 3.
        _, abilities = _parse(ranks={**_RANKS, "R": 0})
        # P2-7: an unlearned R is ABSENT (the packet-module rank gate —
        # no cast, no heal, no cleanse).
        assert "R" not in abilities
        meta = get_champion_options_meta("Milio")
        assert [option["key"] for option in meta["options"]] == ["p_procs"]
        with _testing_client() as client:
            config = client.get("/api/config").get_json()
        options = config["champion_options"]["Milio"]["options"]
        assert [option["key"] for option in options] == ["p_procs"]

    def test_r_rank0_no_cleanse_anywhere_today(self):
        # Pinned actual (the brief's contract #2's absence half): with R
        # rank 0 (or any rank) the app-level fight carries NO cleanse
        # keys and zero utility cleanse events — the kernel never fires
        # implicitly.  Flips when the P2-7 authoring lands.
        combat = _app_combat(ranks={**_RANKS, "R": 0})
        for participant_id in ("main", "ally:Jinx"):
            survival = _survival(combat, participant_id)
            assert "cleanse" not in survival
            assert "cleanse_use" not in survival
            assert "cleanse_denied" not in survival
        assert _cleanse_event_count(combat) == 0

    def test_r_rank0_no_cast_no_heal_contract(self):
        # P2-7 contract (the brief's contract #2): R rank 0 -> NO R cast
        # -> no heal and no cleanse (the completion gates the R cast /
        # packet authoring on rank > 0).  NOT true today: the packet
        # module rotates every SLOT at every rank, so the engine books
        # the R cast and the heal fires with the rank-clamped value —
        # the rank-0 gate is a completion fix.
        combat = _app_combat(ranks={**_RANKS, "R": 0})
        assert _main_heals(combat) == []
        assert _breath_support(combat) == []
        result = _fight(ranks={**_RANKS, "R": 0})
        assert not [c for c in result["cast_timeline"] if c["slot"] == "R"]


# ---------------------------------------------------------------------------
# S3 — R timing
# ---------------------------------------------------------------------------


class TestRTiming:
    def test_r_cast_times_in_engine_timeline(self):
        # The engine cast_timeline is the activation clock: one_rotation
        # R casts land at 0.0; timed rank-3 R casts at 0.25 (after Q/W/E
        # start) with the 100 mana spend.
        one = _fight({}, one_rotation=True)
        (r_one,) = [c for c in one["cast_timeline"] if c["slot"] == "R"]
        assert r_one["time"] == pytest.approx(0.0)
        assert r_one["resource_cost"] == pytest.approx(100.0)
        timed = _fight({}, duration=6.0)
        (r_timed,) = [c for c in timed["cast_timeline"] if c["slot"] == "R"]
        assert r_timed["time"] == pytest.approx(0.25)
        assert r_timed["resource_cost"] == pytest.approx(100.0)

    def test_r_heal_lands_at_the_cast_time(self):
        # The E1-authored heal lands AT the R cast time in both fight
        # modes: the app-level timed fight heals at 0.25; the engine
        # one_rotation cast is at 0.0 (the healing rule authors at the
        # cast start time).
        combat = _app_combat()
        (self_heal,) = _main_heals(combat)
        assert self_heal["time"] == pytest.approx(0.25)
        (ally_heal,) = _breath_support(combat)
        assert ally_heal["time"] == pytest.approx(0.25)
        heals = derive_self_healing(
            get_champion("Milio"),
            {"level": 18, "health": 2000.0, "ability_power": 0.0},
            {"R": {"rank": 3}},
            [],
            [{"slot": "R", "time": 0.0}],
            6.0,
        )
        assert heals[0]["time"] == pytest.approx(0.0)

    def test_r_cleanse_activation_time_equals_cast_time(self):
        # P2-7 contract (the brief's contract #3): the R cast time IS
        # the cleanse activation time — 0.25 in the timed fight, 0.0 in
        # one_rotation — with no explicit-time option (the cast IS the
        # activation, the GP/Rengar precedent).
        combat = _app_combat()
        cleanse = _survival(combat)["cleanse"]
        assert cleanse["activation_time"] == pytest.approx(0.25)
        # The no-CC Garen fight: the cast fires, the decision names
        # control_not_active and the one use is consumed.
        assert cleanse["decision"]["reason"] == "control_not_active"
        assert cleanse["use_consumed"] is True
        # One cast is one cleanse action: the per-recipient packets share a
        # ``cleanse_group`` and the utility receipt folds them back into it.
        assert _cleanse_event_count(combat) == 1


# ---------------------------------------------------------------------------
# S4 — Heal + cleanse separate
# ---------------------------------------------------------------------------


class TestHealAndCleanseSeparate:
    def test_r_heal_fires_with_no_control_active(self):
        # Pinned actual (the brief's contract #4): the R heal is its own
        # receipt (self copy + fan-out copies) and fires even when NO
        # control is active — the Garen fight has no crowd control and
        # both copies land at 0.25 with the sourced 350.
        combat = _app_combat()
        heals = _main_heals(combat)
        assert len(heals) == 1
        assert heals[0].get("skipped_reason") is None
        assert heals[0]["applied_amount"] > 0.0
        (ally_heal,) = _breath_support(combat)
        assert ally_heal.get("skipped_reason") is None
        assert ally_heal["applied_amount"] > 0.0

    def test_r_heal_amount_recomputed_from_cache(self):
        # The E8d fan-out formula recomputed from the cached rows: the
        # rank-3 heal raw == 350 + 50% AP (AP 0 -> 350) on BOTH the self
        # copy and every fan-out copy — one formula prices every
        # recipient (the heal half of the brief's contract #4).
        combat = _app_combat()
        (self_heal,) = _main_heals(combat)
        ap = float(combat["participants"][0]["stats"]["ability_power"])
        assert self_heal["raw_amount"] == pytest.approx(_r_flat(3, ap))
        for ally_heal in _breath_support(combat):
            assert ally_heal["raw_amount"] == pytest.approx(_r_flat(3, ap))

    def test_r_heal_and_cleanse_are_separate_receipts(self):
        # P2-7 contract: the heal and the cleanse stay SEPARATE effects
        # — the cleanse decision/use receipts live on the survival rows
        # (cleanse / cleanse_use / cleanse_denied), the heal remains its
        # own healing_events/support_events entries, and the heal fires
        # even when no control is active (the heal half is true today;
        # the cleanse receipt half is absent).
        combat = _app_combat()
        assert _main_heals(combat)  # the separate heal receipts still land
        assert _breath_support(combat)
        survival = _survival(combat)
        assert survival["cleanse"]["decision"]["reason"] == "control_not_active"
        assert survival["cleanse"]["use_consumed"] is True
        assert survival["cleanse_use"]["uses_after"] == 0


# ---------------------------------------------------------------------------
# S5 — Self + all selected teammates scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_r_heal_fan_out_roster_is_self_plus_all_teammates(self):
        # Pinned actual (the roster half of the brief's contract #5): the
        # R heal fans out to Milio AND every selected teammate — with two
        # selected allies there are two support copies (one per ally) and
        # the self copy stays in the main's healing ledger.
        combat = _app_combat(
            allies=[
                {
                    "champion": "Jinx",
                    "level": _LEVEL,
                    "items": [],
                    "ally_effects_enabled": True,
                },
                {
                    "champion": "Ahri",
                    "level": _LEVEL,
                    "items": [],
                    "ally_effects_enabled": True,
                },
            ]
        )
        copies = _breath_support(combat)
        assert {c["target"] for c in copies} == {"ally:Jinx", "ally:Ahri"}
        assert all(c["amount"] == pytest.approx(350.0) for c in copies)
        assert len(_main_heals(combat)) == 1  # the self copy is separate

    def test_kernel_self_scope_denies_foreign_target(self):
        # Kernel evidence (PASS): the Slice 4 kernel's self-scope rule —
        # a declaration whose target_scope is "self" denies a packet
        # whose recipient is not the holder with the named
        # target_not_selected reason, consuming nothing.  The P2-7
        # self_and_all_teammates scope must accept self AND every
        # selected teammate (a superset the kernel does not know today).
        declaration = {
            "item": _R_CLEANSE_ITEM,
            "active_name": "Breath of Life",
            "target_scope": "self",
            "excluded_control_kinds": ("airborne", "knockback", "knockup"),
            "cooldown_seconds": None,
            "cooldown_source_gap": True,
            "heal": None,
            "movement": None,
        }
        decision = CleanseEligibility(declaration=declaration).decide(
            SimpleNamespace(
                time=0.25,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:0",
                target="ally:Jinx",
                holder="main",
                active_controls=[],
            )
        )
        assert decision.eligible is False
        assert decision.reason == "target_not_selected"
        assert decision.use_consumed is False

    def test_r_cleanse_targets_self_and_every_selected_teammate(self):
        # P2-7 contract (the brief's contract #5): the R cleanse targets
        # Milio AND every selected teammate — the SAME roster the heal
        # fans out to — and each recipient carries its own decision
        # receipt.  The caster must NOT be CC'd for the cast to fire, so
        # the pin is kernel-shaped: ONLY ally:Jinx is charmed, the cast
        # fires at 1.5, the self decision names control_not_active (use
        # consumed once) and the ally decision truncates her own charm.
        result = _simulate_survival(
            [
                _dummy_combatant("enemy", "enemy"),
                _dummy_combatant("main", "main"),
                _dummy_combatant("ally:Jinx", "ally"),
            ],
            {
                "ally:Jinx": [
                    {
                        **_control_packet(0.5, "immobilize", 1.8, source="E"),
                        "target": "ally:Jinx",
                        "_event_id": "cc-E-0.5-ally",
                    }
                ]
            },
            {"main": []},
            {
                "main": [_milio_cleanse_packet(1.5, 0)],
                "ally:Jinx": [_milio_cleanse_packet(1.5, 1, target="ally:Jinx")],
            },
            10.0,
        )
        main = result["main"]
        ally = result["ally:Jinx"]
        assert main["cleanse"]["item"] == _R_CLEANSE_ITEM
        assert ally["cleanse"]["item"] == _R_CLEANSE_ITEM
        assert main["cleanse"]["decision"]["reason"] == "control_not_active"
        assert main["cleanse"]["use_consumed"] is True
        assert ally["cleanse"]["decision"]["eligible"] is True
        assert ally["cleanse"]["removed_controls"][0]["control_kind"] == "immobilize"
        # The ONE cast consumed the single use once (the latch KEY: per
        # cast, shared by all recipients — S8 ambiguity).
        assert main["cleanse_use"]["uses_after"] == 0


# ---------------------------------------------------------------------------
# S6 — Exact control exclusions
# ---------------------------------------------------------------------------


class TestControlExclusions:
    def test_r_non_airborne_wording_pinned(self):
        # The "non-airborne" wording (the brief's contract #6): the
        # cached description says the cleanse removes non-airborne crowd
        # control — the airborne family is the exclusion set the typed
        # declaration must publish.  The candidate set below (the
        # Gangplank displacement family: airborne/knockback/knockup) is a
        # pinned CANDIDATE — the exact exclusion spelling is a contract
        # ambiguity for the coordinator.
        description = _r_ability()["effects"][0]["description"]
        assert "non- airborne crowd control" in description
        assert "airborne" in description

    def test_kernel_excluded_control_kind_rule(self):
        # Kernel evidence (PASS): the Slice 4 kernel already implements
        # the exclusion contract the R must ride — an airborne interval
        # is rejected with the named excluded_control_kind reason (the
        # non-airborne boundary), an active stun is truncated, and a
        # root/charm interval is truncated (all KNOWN_CONTROL_KINDS minus
        # the excluded family).
        declaration = {
            "item": _R_CLEANSE_ITEM,
            "active_name": "Breath of Life",
            "target_scope": "self",
            "excluded_control_kinds": ("airborne", "knockback", "knockup"),
            "cooldown_seconds": None,
            "cooldown_source_gap": True,
            "heal": None,
            "movement": None,
        }
        eligibility = CleanseEligibility(declaration=declaration)
        base = dict(
            time=1.5,
            source_key=_R_CLEANSE_ITEM,
            sequence=0,
            event_id="r:0",
            target="main",
            holder="main",
        )
        for kind in ("airborne", "knockback", "knockup"):
            decision = eligibility.decide(
                SimpleNamespace(
                    **base,
                    active_controls=[
                        {"kind": kind, "start": 1.0, "end": 3.0, "source": "R"}
                    ],
                )
            )
            assert decision.eligible is False, kind
            assert decision.reason == "excluded_control_kind", kind
            assert decision.rejected_controls[0]["reason"] == "excluded_control_kind"
        for kind in ("stun", "root", "immobilize"):
            decision = eligibility.decide(
                SimpleNamespace(
                    **base,
                    active_controls=[
                        {"kind": kind, "start": 1.0, "end": 3.0, "source": "E"}
                    ],
                )
            )
            assert decision.eligible is True, kind
            assert decision.removed_controls[0]["control_kind"] == kind
            assert decision.intervals_after[0]["end"] == pytest.approx(1.5)

    def test_r_airborne_rejected_stun_charm_root_truncated(self):
        # P2-7 contract (the brief's contract #6): an airborne interval
        # at the activation is NOT removed (excluded_control_kind — the
        # "non-airborne" wording), while stun/charm (immobilize) /root
        # intervals ARE truncated at the activation — per recipient.
        # The caster must not be CC'd for the cast to fire, so the
        # recipient-side pins ride the ally packet (the caster is clean).
        def _run(ally_kind: str):
            return _simulate_survival(
                [
                    _dummy_combatant("enemy", "enemy"),
                    _dummy_combatant("main", "main"),
                    _dummy_combatant("ally:Jinx", "ally"),
                ],
                {
                    "ally:Jinx": [
                        {
                            **_control_packet(0.5, ally_kind, 1.8, source="E"),
                            "target": "ally:Jinx",
                            "_event_id": f"cc-{ally_kind}-0.5",
                        }
                    ]
                },
                {"main": []},
                {
                    "main": [_milio_cleanse_packet(1.5, 0)],
                    "ally:Jinx": [_milio_cleanse_packet(1.5, 1, target="ally:Jinx")],
                },
                10.0,
            )

        for kind in ("airborne", "knockback", "knockup"):
            ally = _run(kind)["ally:Jinx"]
            assert (
                ally["cleanse"]["decision"]["reason"] == "excluded_control_kind"
            ), kind
            assert ally["cleanse"]["rejected_controls"][0]["reason"] == (
                "excluded_control_kind"
            )
            assert ally["cleanse"]["removed_controls"] == []
            assert ally["crowd_control_intervals"][0]["end"] == pytest.approx(2.3)
        for kind in ("stun", "root", "immobilize"):
            ally = _run(kind)["ally:Jinx"]
            assert ally["cleanse"]["decision"]["eligible"] is True, kind
            assert ally["cleanse"]["removed_controls"][0]["control_kind"] == kind
            assert ally["crowd_control_intervals"][0]["end"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# S7 — Castability while crowd controlled
# ---------------------------------------------------------------------------


class TestCastabilityGate:
    def test_r_heal_blocked_while_caster_crowd_controlled(self):
        # Pinned actual (the brief's contract #7 — the heal half): the R
        # heal rides the walk's attacker-state gate — while the CASTER
        # is crowd-controlled (Ahri's charm at t=0) the self copy AND the
        # fan-out copies are skipped with attacker_state_blocked and
        # never land.  This is the OPPOSITE of the Slice 5/6 heal
        # carve-out (GP W / Rengar empowered W carry cast_while_disabled):
        # Milio's R "cannot be used while affected by cast-inhibiting
        # crowd control", so a CC'd caster authors NO effect.
        combat = _app_combat(enemy="Ahri")
        (self_heal,) = _main_heals(combat)
        assert self_heal["time"] == pytest.approx(0.25)
        assert self_heal["skipped_reason"] == "attacker_state_blocked"
        assert self_heal["applied_amount"] == 0.0
        (ally_heal,) = _breath_support(combat)
        assert ally_heal["skipped_reason"] == "attacker_state_blocked"
        assert ally_heal["applied_amount"] == 0.0
        # The R heal contributes ZERO to the ledger (the Cozy Campfire
        # self ticks are a separate stream and still land — they are not
        # part of the R cast).
        assert _survival(combat, "main")["healing_received"] > 0.0

    def test_kernel_suppression_blocks_self_cast_use_not_consumed(self):
        # Kernel evidence (PASS): the Slice 4 kernel already implements
        # the suppression half of the castability gate — an active
        # suppression at a self-scope activation fails closed with the
        # named caster_control_blocks_cleanse denial, the interval is
        # untouched and the one use is NOT consumed (the QSS/Mercurial
        # cannotBeSuppressed rule).  The P2-7 gate extends this from
        # suppression-only to every cast-inhibiting kind while the
        # CASTER is CC'd.
        declaration = {
            "item": _R_CLEANSE_ITEM,
            "active_name": "Breath of Life",
            "target_scope": "self",
            "excluded_control_kinds": ("airborne", "knockback", "knockup"),
            "cooldown_seconds": None,
            "cooldown_source_gap": True,
            "heal": None,
            "movement": None,
        }
        decision = CleanseEligibility(declaration=declaration).decide(
            SimpleNamespace(
                time=1.5,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:0",
                target="main",
                holder="main",
                active_controls=[
                    {"kind": "suppression", "start": 1.0, "end": 3.0, "source": "R"}
                ],
            )
        )
        assert decision.eligible is False
        assert decision.reason == "caster_control_blocks_cleanse"
        assert decision.use_consumed is False
        assert decision.removed_controls == []

    def test_r_cannot_fire_while_caster_crowd_controlled(self):
        # P2-7 contract (the brief's contract #7 — the spell's defining
        # property): the R CANNOT fire while the CASTER is
        # crowd-controlled ("cast-inhibiting" — the Mikael's-style gated
        # path, the OPPOSITE of the GP/Rengar utility-before-gate
        # dispatch): the cleanse decision is DENIED with a named reason,
        # the one use is NOT consumed, nothing truncates, and the heal
        # stays blocked (the cast never happens).  Absent today — no
        # cleanse receipts exist at all.
        combat = _app_combat(enemy="Ahri")
        main = _survival(combat, "main")
        # The gated path (the Slice 4 R22 contract): the whole cast is
        # blocked by the attacker crowd-control gate — NO cleanse row on
        # the blocked targets, the use receipt names the gate (NOT
        # consumed), nothing truncates, the heal stays blocked.
        assert "cleanse" not in main
        assert main["crowd_control_intervals"][0]["end"] == pytest.approx(1.8)
        use = main["cleanse_use"]
        assert use["uses_after"] == 1
        assert use["fired_while_crowd_controlled"] is False
        # The R heal specifically is blocked (the cast never happens);
        # the W Cozy Campfire self ticks are a separate stream and land.
        r_heals = [
            e
            for e in combat.get("healing_events", [])
            if e.get("source") == "Breath of Life"
        ]
        assert r_heals and all(
            e.get("skipped_reason") == "attacker_state_blocked" for e in r_heals
        )
        # The ally's charm is untouched too (the whole cast is denied).
        ally = _survival(combat, "ally:Jinx")
        assert ally["crowd_control_intervals"][0]["end"] == pytest.approx(1.8)
        assert "cleanse" not in ally

    def test_r_suppression_fails_closed_use_not_consumed(self):
        # P2-7 contract: an active suppression at the R cast fails
        # closed the same way (suppression is cast-inhibiting — the
        # kernel's CAST_BLOCKING_CONTROL_KINDS already names it); the
        # whole cast is gated by the attacker crowd-control gate (the
        # runtime authoring rides the heal+marker packet, so the utility
        # dispatch-before-gate does NOT apply): the interval is
        # untouched and the one use is NOT consumed.
        result = _kernel_survival(
            controls=[_control_packet(1.0, "suppression", 2.0, source="R")],
            heals=[
                {
                    "time": 1.5,
                    "amount": 100.0,
                    "source": "Breath of Life",
                    "kind": "champion_ability",
                    "attacker": "main",
                    "target_scope": "self_and_all_teammates",
                    "cleanse": True,
                    "cleanse_item": "Milio R",
                    "cleanse_group": "milio:r:cast0",
                    "_event_id": "main:heal:r:0",
                }
            ],
            duration=10.0,
        )
        # The gated path writes the USE receipt only (the Slice 4 R22
        # contract — no cleanse row on the blocked target): the use is
        # NOT consumed and the suppression interval is untouched.
        assert "cleanse" not in result["main"]
        assert result["main"]["crowd_control_intervals"][0]["end"] == pytest.approx(3.0)
        use = result["main"]["cleanse_use"]
        assert use["uses_after"] == 1
        assert use["fired_while_crowd_controlled"] is False


# ---------------------------------------------------------------------------
# S8 — One-use and cooldown boundaries
# ---------------------------------------------------------------------------


class TestOneUseAndCooldown:
    def test_kernel_one_use_latch(self):
        # Kernel evidence (PASS): the Slice 4 per-fight one-use latch —
        # a second activation of the same source fails closed with the
        # named use_spent denial and the cleanse_denied receipt, while
        # the first activation consumes the single use.
        first = _kernel_survival(
            cleanses=[
                {
                    "time": 1.5,
                    "kind": "cleanse",
                    "amount": 1.0,
                    "cleanse_item": "Gangplank W",
                    "source_key": "Gangplank W",
                    "utility_kind": "cleanse",
                    "source": "Gangplank W — Remove Scurvy",
                    "attacker": "main",
                    "target": "main",
                    "sequence": 0,
                    "_event_id": "gp:cleanse:0",
                }
            ]
        )
        assert first["main"]["cleanse"]["use_consumed"] is True
        declaration = {
            "item": _R_CLEANSE_ITEM,
            "active_name": "Breath of Life",
            "target_scope": "self_and_all_teammates",
            "excluded_control_kinds": ("airborne", "knockback", "knockup"),
            "cooldown_seconds": None,
            "cooldown_source_gap": True,
            "heal": None,
            "movement": None,
        }
        decision = CleanseEligibility(declaration=declaration).decide(
            SimpleNamespace(
                time=1.5,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:1",
                target="main",
                holder="main",
                active_controls=[
                    {"kind": "stun", "start": 1.0, "end": 3.0, "source": "E"}
                ],
            ),
            holder={"uses_remaining": 0, "item_held": True},
        )
        assert decision.eligible is False
        assert decision.reason == "use_spent"
        assert decision.use_consumed is False

    def test_r_cooldown_row_receipted_never_enforced(self):
        # Pinned actual (the brief's contract #8): the cached cooldown
        # row 160/145/130 (affectedByCdr) is the value the typed
        # declaration must RECEIPT; the ENGINE enforces the cooldown via
        # the cast_timeline (rank-3 R casts once per 130s — one cast in
        # a 30s fight), and the KERNEL never enforces a cooldown (the
        # Slice 4 latch is the only per-fight boundary).  The module
        # parse cooldown is 0.0 today (the packet module does not
        # publish it).
        r = _r_ability()
        assert r["cooldown"]["modifiers"][0]["values"] == _R_COOLDOWN
        _, abilities = _parse()
        assert abilities["R"]["cooldown"] == pytest.approx(0.0)
        timed = _fight({}, duration=30.0)
        r_casts = [c for c in timed["cast_timeline"] if c["slot"] == "R"]
        assert len(r_casts) == 1
        assert r_casts[0]["time"] == pytest.approx(0.25)

    def test_r_second_cast_use_spent_heals_still_fire(self):
        # P2-7 contract (the brief's contract #8): the per-fight one-use
        # latch — the FIRST R cast consumes the use, the SECOND R cast
        # fails closed with use_spent + cleanse_denied, and the heals
        # keep firing per cast (their own receipts at both cast times).
        result = _kernel_survival(
            controls=[_damage_packet(0.5, 200.0)],
            heals=[_heal_event(1.6, 100.0), _heal_event(3.0, 100.0)],
            cleanses=[
                _milio_cleanse_packet(1.5, 0, group="milio:r:cast0"),
                _milio_cleanse_packet(3.0, 1, group="milio:r:cast1"),
            ],
            duration=10.0,
        )
        main = result["main"]
        assert main["cleanse"]["activation_time"] == pytest.approx(1.5)
        assert main["cleanse"]["use_consumed"] is True
        assert main["cleanse_use"]["uses_after"] == 0
        assert main["cleanse_denied"]
        assert main["cleanse_denied"][0]["reason"] == "use_spent"
        assert main["healing_received"] == pytest.approx(200.0)

    def test_r_one_cast_recipients_share_the_single_use(self):
        # P2-7 contract (the latch KEY ambiguity — reported to the
        # coordinator): ONE R cast authors one packet per recipient
        # (self + every selected teammate), and the whole cast is ONE
        # activation — every recipient's decision FIRES (each truncates
        # its own controls) and the one use is consumed ONCE by the
        # cast, NOT once per packet.  The current kernel consumes per
        # packet, so the completion must key the latch per cast (shared
        # decision) — a second R cast then denies every one of its
        # recipients.
        result = _simulate_survival(
            [
                _dummy_combatant("enemy", "enemy"),
                _dummy_combatant("main", "main"),
                _dummy_combatant("ally:Jinx", "ally"),
            ],
            {
                "main": [_control_packet(0.5, "immobilize", 1.8, source="E")],
                "ally:Jinx": [
                    {
                        **_control_packet(0.5, "immobilize", 1.8, source="E"),
                        "target": "ally:Jinx",
                        "_event_id": "cc-E-0.5-ally",
                    }
                ],
            },
            {"main": []},
            {
                "main": [_milio_cleanse_packet(1.5, 0)],
                "ally:Jinx": [_milio_cleanse_packet(1.5, 1, target="ally:Jinx")],
            },
            10.0,
        )
        for participant_id in ("main", "ally:Jinx"):
            state = result[participant_id]
            assert state["cleanse"]["decision"]["eligible"] is True
            # The removed tail starts at the activation (its end is the
            # original interval end 2.3); the kept interval ends at 1.5.
            assert state["cleanse"]["removed_controls"][0]["start"] == pytest.approx(
                1.5
            )
            assert state["cleanse"]["intervals_after"][0]["end"] == pytest.approx(1.5)
        # One cast = ONE use (activations 1, not per packet).
        use = result["main"]["cleanse_use"]
        assert use["uses_after"] == 0
        assert use["activations"] == 1


# ---------------------------------------------------------------------------
# S9 — Same-time ordering
# ---------------------------------------------------------------------------


class TestSameTimeOrdering:
    def test_kernel_cleanse_dispatches_before_attacker_gate(self):
        # Kernel evidence (PASS): utility-kind cleanse packets dispatch
        # BEFORE the attacker-state gate (the GP/Rengar castability
        # precedent) — a GP W packet at 1.5 fires while the caster's
        # charm is active, and the same-time heal is attacker-state
        # blocked.  The MILIO contract (S7) is the OPPOSITE: the R cast
        # is denied while the caster is CC'd, so BOTH the heal and the
        # cleanse are denied at the same timestamp.
        result = _kernel_survival(
            controls=[_control_packet(0.5, "immobilize", 1.8, source="E")],
            heals=[_heal_event(1.5, 100.0)],
            cleanses=[
                {
                    "time": 1.5,
                    "kind": "cleanse",
                    "amount": 1.0,
                    "cleanse_item": "Gangplank W",
                    "source_key": "Gangplank W",
                    "utility_kind": "cleanse",
                    "source": "Gangplank W — Remove Scurvy",
                    "attacker": "main",
                    "target": "main",
                    "sequence": 0,
                    "_event_id": "gp:cleanse:0",
                }
            ],
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["decision"]["eligible"] is True
        assert cleanse["removed_controls"][0]["reason"] == ""
        assert result["main"]["healing_received"] == pytest.approx(0.0)

    def test_r_heal_and_cleanse_process_at_the_same_timestamp(self):
        # The kernel order pin (the brief's contract #9): in the support
        # template stream the champion heal fan-out is appended BEFORE
        # the champion cleanse block (the GP/Rengar authoring sits after
        # the self_healing fan-out loop), so at the R cast time the heal
        # copies process first, then the cleanse packets — the observable
        # pair at the same timestamp is (heal receipt, cleanse decision).
        # With no control active the heal lands and the cleanse consumes
        # the use (the wired half is the S3/S4 xfail pins); the template
        # ORDER itself is pinned by the fan-out index rule below.
        import src.calculator.participant_timeline as pt_module

        source = open(pt_module.__file__, encoding="utf-8").read()
        heal_loop = source.find("for heal_index, heal_event in enumerate(")
        cleanse_block = source.find('champion_name == "Gangplank"')
        assert heal_loop != -1 and cleanse_block != -1
        assert heal_loop < cleanse_block

    def test_r_cleanse_receipt_pairs_with_heal_at_cast_time(self):
        # P2-7 contract: the app-level Garen fight (no control) shows the
        # heal receipt AND the cleanse decision at the SAME timestamp
        # 0.25 — the heal applies (applied_amount > 0) and the cleanse
        # consumes the use with the control_not_active reason.
        combat = _app_combat()
        (self_heal,) = _main_heals(combat)
        cleanse = _survival(combat)["cleanse"]
        assert self_heal["time"] == pytest.approx(0.25)
        assert cleanse["activation_time"] == pytest.approx(0.25)
        assert cleanse["decision"]["reason"] == "control_not_active"
        assert cleanse["use_consumed"] is True


# ---------------------------------------------------------------------------
# S10 — Repeated casts
# ---------------------------------------------------------------------------


class TestRepeatedCasts:
    def test_kernel_second_activation_use_spent(self):
        # Kernel evidence (PASS): the one-use latch in the walk — two
        # activations of the same source: the first consumes, the second
        # receipts the named use_spent denial in cleanse_denied and
        # truncates nothing further.
        result = _kernel_survival(
            controls=[_control_packet(0.5, "immobilize", 1.8, source="E")],
            cleanses=[
                {
                    "time": 1.5,
                    "kind": "cleanse",
                    "amount": 1.0,
                    "cleanse_item": "Gangplank W",
                    "source_key": "Gangplank W",
                    "utility_kind": "cleanse",
                    "source": "Gangplank W — Remove Scurvy",
                    "attacker": "main",
                    "target": "main",
                    "sequence": 0,
                    "_event_id": "gp:cleanse:0",
                },
                {
                    "time": 3.0,
                    "kind": "cleanse",
                    "amount": 1.0,
                    "cleanse_item": "Gangplank W",
                    "source_key": "Gangplank W",
                    "utility_kind": "cleanse",
                    "source": "Gangplank W — Remove Scurvy",
                    "attacker": "main",
                    "target": "main",
                    "sequence": 1,
                    "_event_id": "gp:cleanse:1",
                },
            ],
        )
        main = result["main"]
        assert main["cleanse_use"]["uses_after"] == 0
        assert main["cleanse_denied"]
        assert main["cleanse_denied"][0]["reason"] == "use_spent"
        # The second activation truncated nothing: the charm interval
        # ended at the FIRST activation (1.5) and the second denial left
        # the post-truncation intervals untouched.
        assert main["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "immobilize",
                "start": 0.5,
                "end": 1.5,
                "source": "E",
            }
        ]

    def test_r_second_cast_truncates_once(self):
        # P2-7 contract (the brief's contract #10): the second R cast ->
        # use_spent; truncation happens ONCE (the first cast's
        # truncation stands; the second denial truncates nothing), the
        # heals still fire per cast, and a control landing after both
        # casts keeps its full interval (no immunity).
        result = _kernel_survival(
            controls=[
                _damage_packet(0.5, 200.0),
                _control_packet(0.5, "immobilize", 1.8, source="E"),
            ],
            heals=[_heal_event(1.6, 100.0), _heal_event(3.0, 100.0)],
            cleanses=[
                _milio_cleanse_packet(1.5, 0, group="milio:r:cast0"),
                _milio_cleanse_packet(3.0, 1, group="milio:r:cast1"),
            ],
            duration=10.0,
        )
        main = result["main"]
        assert main["cleanse"]["activation_time"] == pytest.approx(1.5)
        assert main["cleanse_denied"][0]["reason"] == "use_spent"
        intervals = main["crowd_control_intervals"]
        assert intervals[0]["end"] == pytest.approx(1.5)
        assert main["healing_received"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# S11 — Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_truncate_intervals_contract(self):
        # Kernel evidence (PASS): the exact truncation the R must ride
        # (the Slice 4 matrix's committed rule): historical intervals
        # kept, the active tail removed, a control starting at/after the
        # activation removed, unknown kinds never truncated.
        intervals = [
            {"kind": "stun", "start": 0.0, "end": 1.0, "source": "A"},  # historical
            {"kind": "stun", "start": 1.0, "end": 3.0, "source": "B"},  # active
            {"kind": "stun", "start": 1.5, "end": 2.0, "source": "C"},  # at activation
            {"kind": "stun", "start": 2.0, "end": 4.0, "source": "D"},  # after
            {"kind": "dance", "start": 0.0, "end": 9.0, "source": "E"},  # unknown
        ]
        kept, removed = truncate_intervals(intervals, 1.5, frozenset({"stun"}))
        assert [row["source"] for row in kept] == ["A", "B", "E"]
        assert kept[1]["end"] == pytest.approx(1.5)
        assert [row["source"] for row in removed] == ["B", "C", "D"]

    def test_kernel_truncation_historical_remains_later_untouched(self):
        # Kernel evidence (PASS): walk-level truncation with a resolvable
        # source (GP W): the active charm ends at the activation,
        # historical downtime remains counted, and a control landing
        # AFTER the activation keeps its full interval (a cleanse creates
        # NO immunity — the Slice 4 contract the R rides).
        result = _kernel_survival(
            controls=[
                _control_packet(0.5, "immobilize", 1.8, source="E"),
                _control_packet(2.0, "immobilize", 1.8, source="E"),
            ],
            cleanses=[
                {
                    "time": 1.5,
                    "kind": "cleanse",
                    "amount": 1.0,
                    "cleanse_item": "Gangplank W",
                    "source_key": "Gangplank W",
                    "utility_kind": "cleanse",
                    "source": "Gangplank W — Remove Scurvy",
                    "attacker": "main",
                    "target": "main",
                    "sequence": 0,
                    "_event_id": "gp:cleanse:0",
                }
            ],
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["downtime_before"] == pytest.approx(1.8)
        assert cleanse["downtime_after"] == pytest.approx(2.8)
        intervals = result["main"]["crowd_control_intervals"]
        assert intervals[0]["end"] == pytest.approx(1.5)
        assert intervals[1]["start"] == pytest.approx(2.0)
        assert intervals[1]["end"] == pytest.approx(3.8)

    def test_r_truncates_per_recipient_at_activation(self):
        # P2-7 contract (the brief's contract #11): the active control
        # intervals truncate at the activation PER RECIPIENT — the
        # kernel fixture charms ONLY ally:Jinx ([0.5, 2.3]); the cast
        # fires at 1.5 (the caster is clean) and the ally's interval
        # ends at 1.5 (downtime_before 1.8, downtime_after 1.0) while
        # the main's ledger is untouched; historical downtime remains
        # and later controls are untouched (S10 pins that half).
        result = _simulate_survival(
            [
                _dummy_combatant("enemy", "enemy"),
                _dummy_combatant("main", "main"),
                _dummy_combatant("ally:Jinx", "ally"),
            ],
            {
                "ally:Jinx": [
                    {
                        **_control_packet(0.5, "immobilize", 1.8, source="E"),
                        "target": "ally:Jinx",
                        "_event_id": "cc-E-0.5-ally",
                    }
                ]
            },
            {"main": []},
            {
                "main": [_milio_cleanse_packet(1.5, 0)],
                "ally:Jinx": [_milio_cleanse_packet(1.5, 1, target="ally:Jinx")],
            },
            10.0,
        )
        ally = result["ally:Jinx"]
        assert ally["crowd_control_intervals"] == [
            {
                "recipient": "ally:Jinx",
                "kind": "immobilize",
                "start": 0.5,
                "end": 1.5,
                "source": "E",
            }
        ]
        assert ally["cleanse"]["downtime_before"] == pytest.approx(1.8)
        assert ally["cleanse"]["downtime_after"] == pytest.approx(1.0)
        assert result["main"]["crowd_control_intervals"] == []


# ---------------------------------------------------------------------------
# S12 — Missing identity + rows
# ---------------------------------------------------------------------------


class TestMissingIdentityAndRows:
    def test_r_source_unresolved_fails_closed(self):
        # Pinned actual (the brief's contract #12): the Milio R source
        # is NOT declared today, so the resolver fails closed with a
        # KeyError naming the source (the unavailable-evidence denial —
        # a packet that cannot be attributed to a sourced declaration
        # must never guess).  The P2-7 completion makes every spelling
        # resolve to the declaration; unknown spellings still fail
        # closed.
        # P2-7: the Milio R source now RESOLVES (the declaration
        # landed); an unknown spelling still fails closed with the named
        # KeyError (the unavailable-evidence denial).
        assert resolve_cleanse_item(_R_CLEANSE_ITEM) == "Milio R"
        assert resolve_cleanse_item("Milio R — Breath of Life") == "Milio R"
        assert resolve_cleanse_item("Breath of Life") == "Milio R"
        with pytest.raises(KeyError) as excinfo:
            resolve_cleanse_item("Bogus Life")
        assert "Bogus Life" in str(excinfo.value)

    def test_require_row_fail_loud_precedent(self):
        # The _require_row precedent (the brief's contract #12): missing
        # leveling rows fail LOUD, naming the ability — the K'Sante
        # helper the typed R declaration must mirror for the "Heal" row.
        from src.calculator.champions.ksante import _require_row

        # The R Heal row EXISTS (extract_named resolves it) — the row the
        # declaration must require.
        assert _r_flat(3, 0.0) == pytest.approx(350.0)
        # A genuinely missing attribute raises, naming the ability.
        fake = {"name": "Breath of Life", "effects": [{"leveling": []}]}
        with pytest.raises(KeyError) as excinfo:
            _require_row(fake, "Heal")
        assert "Breath of Life" in str(excinfo.value)
        assert "Heal" in str(excinfo.value)

    def test_r_declaration_resolves_and_rows_publish(self):
        # P2-7 contract: the R cleanse source now RESOLVES (the
        # declaration landed) — every spelling resolves to the
        # declaration key, the declaration's source_receipts carry the
        # wording + game-file evidence, and a missing "Heal" row fails
        # loud (the _require_row precedent).
        assert resolve_cleanse_item(_R_CLEANSE_ITEM) == _R_CLEANSE_ITEM
        assert resolve_cleanse_item("Milio R — Breath of Life") == _R_CLEANSE_ITEM
        assert resolve_cleanse_item("Breath of Life") == _R_CLEANSE_ITEM
        rule = CHAMPION_CLEANSE_DECLARATIONS[_R_CLEANSE_ITEM]
        assert any(
            "non-airborne crowd control" in str(receipt.get("wording", ""))
            for receipt in rule["source_receipts"]
        )
        assert any(
            "milio.bin.json" in str(receipt.get("game_file", ""))
            for receipt in rule["source_receipts"]
        )


# ---------------------------------------------------------------------------
# S13 — Score fail-closed behavior
# ---------------------------------------------------------------------------


class TestScoreFailClosed:
    def test_score_gate_names_fail_closed_receipts(self):
        # PASS: the compiled score path ALREADY fails closed on every
        # Milio R authoring shape — a cleanse-kind template
        # (support_kind=cleanse) and a heal packet carrying the cleanse
        # marker (support_cleanse) are unrepresentable; the R heal alone
        # (kind heal, no marker) stays representable.  The P2-7 wiring
        # must route the R packet through this gate (never silently
        # re-price the heal as a plain heal or drop the cleanse).
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": _R_CLEANSE_ITEM,
            "source_key": _R_CLEANSE_ITEM,
            "utility_kind": "cleanse",
            "source": "Milio R — Breath of Life",
            "time": 0.25,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:R:0",
        }
        assert compiled_support_receipt(template) == "support_kind=cleanse"
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"
        assert (
            compiled_support_receipt({"kind": "heal", "amount": 100.0, "cleanse": True})
            == "support_cleanse"
        )
        assert compiled_support_receipt({"kind": "heal", "amount": 350.0}) is None
        assert compiled_support_receipt({"kind": "movement"}) == "support_kind=movement"

    def test_score_gate_never_reprices_the_r_heal(self):
        # PASS: the R heal packet (the E8d fan-out shape) is a plain heal
        # — representable — and the cleanse marker (once the R packet
        # carries it) flips the SAME packet to the named receipt: the
        # gate can never silently re-price the heal as a plain heal.
        heal_template = {
            "kind": "heal",
            "amount": 350.0,
            "source": "Breath of Life",
            "time": 0.25,
            "attacker": "main",
            "target": "ally:Jinx",
            "_event_id": "milio:r:3:enemy:Garen:ally:1",
        }
        assert compiled_support_receipt(heal_template) is None
        assert unrepresentable_template_receipt(heal_template) is None
        marked = {**heal_template, "cleanse": True}
        assert compiled_support_receipt(marked) == "support_cleanse"
        assert unrepresentable_template_receipt(marked) == "support_cleanse"


# ---------------------------------------------------------------------------
# S14 — Full vs score parity
# ---------------------------------------------------------------------------


class TestModeParity:
    def test_r_surface_byte_identical_under_score_only(self):
        # PASS today: the R surface — breakdown row, mana ledger,
        # resource spend, cast timeline — is byte-identical between the
        # full walk and the compiled score path in both fight modes; the
        # R stays OUT of outgoing damage in both modes (the brief's
        # contract #14).
        for one_rotation in (True, False):
            full = _fight({}, one_rotation=one_rotation)
            scored = _fight({}, one_rotation=one_rotation, score_only=True)
            assert full["breakdown"]["R"] == scored["breakdown"]["R"]
            assert full["breakdown"]["R"]["total_damage"] == 0.0
            assert full["total_damage"] == scored["total_damage"]
            assert full["resource_spent"] == scored["resource_spent"]
            assert full["resource_remaining"] == scored["resource_remaining"]
            assert full["resource_ledger"] == scored["resource_ledger"]
            shared = ("time", "slot", "name", "ordinal", "resource_cost")
            for full_row, scored_row in zip(
                full["cast_timeline"], scored["cast_timeline"]
            ):
                assert {k: full_row[k] for k in shared} == {
                    k: scored_row[k] for k in shared
                }

    def test_r_mana_spend_pinned(self):
        # Pinned actual: the R cast DOES spend mana — 100 at every rank,
        # receipted as the "ability R cast" ledger spend.
        result = _fight({}, one_rotation=True)
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        spends = {
            row["source"]: row
            for row in ledger["receipts"]
            if row["operation"] == "spend"
        }
        assert spends["ability R cast"]["amount"] == pytest.approx(100.0)
        assert spends["ability R cast"]["detail"] == {"slot": "R", "ordinal": 1}
        for rank in (1, 2, 3):
            _, abilities = _parse(ranks={**_RANKS, "R": rank})
            assert abilities["R"]["resource_cost"] == pytest.approx(100.0)

    def test_r_mode_parity_named_cleanse_divergence(self):
        # P2-7 contract: the engine surface stays byte-identical full vs
        # score_only AND the couple score gate names the fail-closed
        # receipt for the R cleanse packet (the completion rule's pinned
        # divergence — support_kind=cleanse, never a silent re-price).
        full = _fight({}, one_rotation=True)
        scored = _fight({}, one_rotation=True, score_only=True)
        assert full["breakdown"]["R"] == scored["breakdown"]["R"]
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": _R_CLEANSE_ITEM,
            "source_key": _R_CLEANSE_ITEM,
            "utility_kind": "cleanse",
            "source": "Milio R — Breath of Life",
            "time": 0.0,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:R:0",
        }
        assert compiled_support_receipt(template) == "support_kind=cleanse"
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"
        combat = _app_combat()
        assert _survival(combat)["cleanse"]["decision"]["reason"] == (
            "control_not_active"
        )
        assert _survival(combat)["cleanse"]["item"] == _R_CLEANSE_ITEM


# ---------------------------------------------------------------------------
# S15 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_w_ally_support_unchanged(self):
        # The W (Cozy Campfire) ally-support is an unchanged boundary
        # (the brief's contract #15): the scanner-authored ally heal
        # lands on the selected teammate at the W cast time with the
        # sourced Total Heal 150 at rank 5 (AP 0).
        combat = _app_combat()
        w_heals = [
            e
            for e in combat["support_events"]
            if e.get("attacker") == "main"
            and e.get("source") == "Cozy Campfire · Total Heal"
            and e.get("kind") == "heal"
        ]
        assert len(w_heals) == 1
        (w_heal,) = w_heals
        assert w_heal["time"] == pytest.approx(0.0)
        assert w_heal["target"] == "ally:Jinx"
        assert w_heal["amount"] == pytest.approx(150.0)

    def test_e_ally_support_unchanged(self):
        # The E (Warm Hugs) ally-support is an unchanged boundary: the
        # scanner-authored shield lands on the selected teammate with the
        # sourced Shield Strength 165 at rank 5 (AP 0) for 2.5s.
        combat = _app_combat()
        e_shields = [
            e
            for e in combat["support_events"]
            if e.get("attacker") == "main"
            and e.get("source") == "Warm Hugs · Shield Strength"
            and e.get("kind") == "shield"
        ]
        assert len(e_shields) == 1
        (e_shield,) = e_shields
        assert e_shield["time"] == pytest.approx(0.25)
        assert e_shield["target"] == "ally:Jinx"
        assert e_shield["amount"] == pytest.approx(165.0)
        assert e_shield["duration"] == pytest.approx(2.5)

    def test_q_damage_unchanged(self):
        # The Q damage is an unchanged boundary (the brief's contract
        # #15): the module's Q total_raw equals the typed extract at rank
        # 5 and the fight row prices it; the R row stays zero-damage.
        stats, abilities = _parse()
        q = _MILIO_DATA["abilities"]["Q"][0]
        q_value = extract_named(q, "Magic Damage", 5, stats)
        assert abilities["Q"]["total_raw"] == pytest.approx(q_value)
        assert abilities["Q"]["parts"][0].damage_type == "magic"
        assert abilities["Q"]["cooldown"] == pytest.approx(10.0)
        result = _fight({}, one_rotation=True)
        assert result["breakdown"]["Q"]["total_damage"] > 0.0
        assert result["breakdown"]["R"]["total_damage"] == 0.0

    def test_cleanse_tables_untouched(self):
        # The Slice 4 item cleanses and the Slice 5/6 champion cleanses
        # are unchanged boundaries (the brief's contract #15): the
        # declarations/sources stay exactly the three items + Gangplank W
        # + Rengar W; Milio R is the coordinator's ADDITION, never a
        # mutation of the existing rows.
        assert set(ITEM_CLEANSE_DECLARATIONS) == {
            "Mikael's Blessing",
            "Quicksilver Sash",
            "Mercurial Scimitar",
        }
        assert set(CHAMPION_CLEANSE_DECLARATIONS) == {
            "Gangplank W",
            "Rengar W",
            "Milio R",
            "Dr. Mundo P",
            "Olaf R",
        }
        for item in ITEM_CLEANSE_DECLARATIONS:
            assert resolve_cleanse_item(item) == item
        assert resolve_cleanse_item("Remove Scurvy") == "Gangplank W"
        assert resolve_cleanse_item("Battle Roar") == "Rengar W"

    def test_named_denial_vocabulary_pinned(self):
        # The named fail-closed denial vocabulary the R wiring must ride
        # (the brief's contract #7 vocabulary): the Slice 4 decision
        # reasons plus the unavailable-source KeyError and the score
        # receipts.
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
        assert compiled_support_receipt({"kind": "cleanse"}) == "support_kind=cleanse"
        assert (
            compiled_support_receipt({"kind": "heal", "cleanse": True})
            == "support_cleanse"
        )
        assert (
            unrepresentable_template_receipt({"kind": "cleanse", "amount": 1.0})
            == "support_kind=cleanse"
        )


# ---------------------------------------------------------------------------
# S16 — Regression surface (run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (the repo gate):
#
#   .venv/bin/python -m pytest tests/test_milio_r_cleanse.py #     tests/test_aurelion_sol_stardust_ledger.py #     tests/test_senna_souls_ledger.py tests/test_bard_chimes_ledger.py #     tests/test_heimerdinger_multihit.py tests/test_ksante_w_resistance.py #     tests/test_rengar_ferocity_ledger.py tests/test_rengar_w_cleanse.py #     tests/test_gangplank_w_cleanse.py tests/test_cleanse_eligibility.py #     tests/test_cleanse_eligibility_kernel.py #     tests/test_cleanse_eligibility_consumers.py tests/test_state_lifecycle.py #     tests/test_state_lifecycle_consumers.py tests/test_resource_ledger.py #     tests/test_resource_ledger_consumers.py #     tests/test_resource_ledger_champion_consumers.py #     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py #     tests/test_mana_restore_refund.py tests/test_app.py
#
# The broader regression surface (every test that touches milio / breath
# of life / ally support, per the brief contract #16): test_e8_support.py
# test_e1_healing_b5.py test_issue_143.py test_ally_support_wave2.py
# test_heal_ledger_phase2.py test_survival_kernel.py test_e2_dot_2.py
# test_cp10_batch_04.py test_support_effects.py tests/test_app.py
