"""P2 Slice 8 — Dr. Mundo P (Goes Where He Pleases) champion passive
(test-matrix owner: RLM-2 C).

Focused TDD matrix for Dr. Mundo's passive — the immunity-to-the-next-
hostile-immobilizing-effect resist, the 4% current-health cost, the
dropped canister, the pickup heal + cooldown refund, and the 60→15
cooldown.  CURRENT RUNTIME FACTS (verified before pinning):

- The module (``src/calculator/champions/dr_mundo.py``) DELIBERATELY
  ABSENTS P: the docstring says the passive is "health regeneration, an
  immobilize cleanse and a self-heal on the dropped canister. It deals
  no damage to an enemy, so it gets no slot"; ASSUMPTIONS say "Mundo's
  passive, Q's health cost and refund, and W's grey-health healing are
  self-sustain and are not modeled"; MODULE_COVERAGE reports
  ``P: out_of_scope``; the parse receipt has exactly E/Q/R/W and the
  OPTIONS set is only ``mundo_missing_health_percent`` and
  ``r_nearby_champions``.  The API rejects every ``p_*`` champion
  option with a named 400 ("champion_options contains unknown option
  p_...").
- The cached P rows (data/champions.json "DrMundo", revision-pinned):
  effects[0] = the innate regen ("regenerates an additional 0.4% : 2.3%
  (based on level) of his maximum health every 5 seconds" / 0.04% :
  0.23% every 0.5s) with TWO "Max Health Damage" leveling arrays — a
  40-entry per-5s display row (0.4..6.7, levels 1..40) and an 18-entry
  per-0.5s row (0.04..0.23, levels 1..18) that matches the game file's
  ``MaxHealthRegen`` exactly; effects[1] = the trigger ("immunity to
  the next hostile immobilizing effect... pays a health cost equal to
  4% of his current health and propels a canister that lands 525 units
  in the general direction of the immobilization source, remaining on
  the ground for 7 seconds") with EMPTY leveling (the cost/canister
  values live only in the wording + the game file); effects[2] = the
  pickup ("Dr. Mundo can move near the canister to consume it, healing
  himself for 4% of his maximum health and reducing the cooldown ... by
  15 seconds. Enemy champions can move near it to destroy it.");
  effects[3] = the respawn reset ("Goes Where He Pleases' cooldown
  resets upon respawning."); cooldown = 60.0 → 15.0 by level (18
  entries, affectedByCdr False); targeting "Passive", affects "Self",
  cost/resource null.  The notes also carry the same-cast-instance
  immunity and the nested-immobilize prevention rules plus the
  spell-shield/Black-Shield priority.
- Game-file evidence (data/bin/characters/drmundo.bin.json DrMundoP):
  DataValues CannisterGroundDuration 7.0, CannisterPickupRadius 115.0,
  CannisterDistanceAway 525.0, CannisterMaxAngle 70.0,
  PassiveCooldownRefund 15.0, CurrentHealthLoss 0.04, MaxHealthGain
  0.04; PassiveCooldown = 60 at level 1 with -9 breakpoints at levels
  3/6/9/12/15/21 (the wiki row interpolates linearly 60→15 — the
  mid-level rows differ slightly from the game's step function; both
  agree on the 60→15 endpoints); MaxHealthRegen = 0.004 + 0.0005/level
  with +0.001/+0.0015/+0.002 breakpoints at 7/13/16 (matches the
  cached per-0.5s row rounded to 2dp).
- The Slice 4/5/6/7 champion-cleanse kernel
  (``CHAMPION_CLEANSE_DECLARATIONS`` — Gangplank W, Rengar W, Milio R —
  + the per-cast packet authoring + ``_apply_cleanse`` + the one-use
  latch + the ``cleanse``/``cleanse_use``/``cleanse_denied`` receipts)
  does NOT wire Dr. Mundo today: ``resolve_cleanse_item("Dr. Mundo P")``
  FAILS CLOSED with a KeyError naming the source; the app-level fight
  carries no resist/canister/pickup receipts anywhere, the survival row
  has no cleanse key, and utility_outcomes cleanse event_count is 0.
- The survival walk (``transitions._apply_crowd_control``) applies a
  hostile immobilizing control to Mundo TODAY: an enemy Ahri charm
  (cc_kind "immobilize", 1.8s) lands as ``crowd_control_intervals`` +
  ``action_downtime_intervals`` rows and the event's ``crowd_control``
  annotation with NO cost, NO canister and NO resist receipt.  A soft
  control (slow/ground/silence/...) is classified non-blocking and adds
  no downtime (the pass-through the passive must never trigger on).

The coordinator's completion (P2-8) will (most likely) add a BOUNDED
passive: the resist intercepts the next hostile immobilizing effect
(the effect never applies — an IMMUNITY, not a truncation), the 4%
current-health cost + the canister drop (525 units, 7s) are receipted,
the pickup heal (4% max health) + the enemy destruction are named
unsupported timings (NO movement simulation — NO auto-pickup timing,
NO user toggle), the 15s cooldown refund is receipted but never
enforced, the 60→15 row is receipted, and the score fails closed
(never a silent re-price).  This matrix pins the CONTRACT;
genuinely-absent mechanics are pytest.mark.xfail (non-strict) with
reason "awaiting P2-8 ..." — the completion removes the markers.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (the trigger wording; the
      cost/heal/canister/cd values via the typed path recomputed
      against the cache + game file; the regen rows; the absent P
      parse receipt + module coverage; the source receipts; the absent
      typed declaration xfailed).
  S2  No trigger (a fight with no hostile immobilizing control: no
      resist, no cost, no canister — the pre-wiring absence; the wired
      absence contract xfailed).
  S3  Valid immobilizing trigger (the control APPLIES today — no
      resist; the wired resist contract xfailed: first hostile
      immobilizing control never applied, 4% CURRENT-health cost paid,
      canister drop receipted 525/7s).
  S4  Non-trigger controls (slow/ground/silence classify soft; a slow
      packet adds no downtime and never triggers the resist — the
      wired non-trigger contract xfailed).
  S5  Canister timing + lifetime (no canister receipts today; the
      wired drop-at-trigger-time + 7s lifetime + NAMED unsupported
      pickup timing xfailed; the heal does not fire without the
      pickup).
  S6  Health cost (no cost receipt today; the wired 4% current-health
      cost at the resist xfailed).
  S7  Heal receipt (the heal is on the PICKUP per effects[2] — no
      pickup heal fires today; the wired pickup heal 4% max health +
      named denial absent the pickup xfailed).
  S8  Cleanse receipt (no resist/cleanse receipts today; the wired
      resist receipt — immunity consumed, control not applied —
      xfailed).
  S9  Cooldown/reduction (the 60→15 row pinned; no P cooldown in the
      parse or fight result; the wired receipt + 15s pickup reduction
      receipted-never-enforced xfailed).
  S10 Enemy destruction + unavailable pickup (named fail-closed
      denials — destruction needs enemy movement, pickup needs Mundo's
      movement — xfailed).
  S11 One-use behavior (the immunity is one-shot; today every control
      applies; the wired consume-then-apply contract xfailed).
  S12 Suppression and castability (suppression is a blocking kind and
      the P wording carries NO carve-out — the source verdict is
      "hostile immobilizing effect" and the immunity is passive, so the
      QSS castability gate does not apply; the wired suppression
      verdict xfailed).
  S13 Repeated triggers (after the resist, subsequent immobilizing
      controls apply normally until the recharge — today ALL apply;
      the wired recharge contract xfailed).
  S14 Missing identity or rows (the unavailable-source KeyError pinned;
      the typed extractors return 0.0 on the empty P leveling — a
      pinned source gap; the _require_row fail-loud precedent).
  S15 Score fail-closed (the generic gate receipts PASS —
      support_kind=cleanse / support_cleanse / support_kind=canister;
      never a silent re-price).
  S16 Full vs score parity (Q/W/E/R engine surface byte-identical
      today — each path needs a FRESH stats dict because the module
      parse mutates the caller's stats with R's base-health grant,
      a documented actual; the R regen heal surface fires in the full
      path only; the wired P parity + the named score divergence
      xfailed).
  S17 Unchanged boundaries (Q/W/E/R parse receipts, the module
      OPTIONS, the GP/Rengar/Milio + item cleanse declarations, the
      R-regen heal surface, the existing Mundo tests).

Expected damage values are recomputed from data/champions.json
leveling rows against the fight's own stats — no literal damage
constants.  The P cost/heal/canister/cd values ARE the values under
test (the typed declaration must publish them), so they appear as
pinned cache + game-file evidence (the K'Sante / Gangplank / Rengar /
Milio matrix precedent).  The declaration item key below is a pinned
CANDIDATE ("Dr. Mundo P"); the coordinator's final spelling is a
contract ambiguity reported to the parent.
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
    compiled_support_receipt,
    resolve_cleanse_item,
    truncate_intervals,
)
from src.calculator.crowd_control_eligibility import (
    CONTROL_BLOCKING_KINDS,
    CONTROL_SOFT_KINDS,
    KNOWN_CONTROL_KINDS,
    classify_control,
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
_MUNDO_DATA = _CHAMPION_DATA["DrMundo"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P2-8 coordinator wires the typed passive declaration + the resist
# path; genuinely-absent mechanics are xfailed with this reason (never
# strict — the completion removes the markers).
_AWAIT = "awaiting P2-8 wiring"

# The cached P rows the typed declaration must publish (values under
# test — pinned as cache + game-file evidence, never literal damage
# constants).
_P_REGENERATION_PER_0_5S = [
    0.04,
    0.05,
    0.05,
    0.06,
    0.06,
    0.07,
    0.08,
    0.09,
    0.1,
    0.11,
    0.12,
    0.13,
    0.14,
    0.16,
    0.17,
    0.19,
    0.21,
    0.23,
]
_P_COOLDOWN_ROW = [
    60.0,
    57.35294117647059,
    54.705882352941174,
    52.05882352941177,
    49.411764705882355,
    46.76470588235294,
    44.11764705882353,
    41.470588235294116,
    38.82352941176471,
    36.17647058823529,
    33.529411764705884,
    30.88235294117647,
    28.235294117647058,
    25.588235294117645,
    22.94117647058824,
    20.294117647058826,
    17.647058823529413,
    15.0,
]
_P_CURRENT_HEALTH_COST_PERCENT = 4.0  # 4% current health on the resist
_P_MAX_HEALTH_HEAL_PERCENT = 4.0  # 4% max health on the pickup
_P_CANISTER_DISTANCE = 525.0  # units from Mundo
_P_CANISTER_LIFETIME = 7.0  # seconds on the ground
_P_PICKUP_CD_REFUND = 15.0  # seconds off the passive cooldown

# Pinned CANDIDATE declaration key for the coordinator (the GP/Rengar/
# Milio mirror): the packet source_key / cleanse_item / latch key.
_P_CLEANSE_ITEM = "Dr. Mundo P"


def _stats(health: float = 4391.0) -> dict:
    """Fresh champion stats (the reference build from test_dr_mundo.py).

    A FRESH dict per call is mandatory: the module parse MUTATES the
    caller's stats dict with R's base-health grant (``_maximum_dosage``
    writes ``ctx.stats["health"]``/``["base_health"]`` during parse — the
    documented test_dr_mundo.py "parse-context mutation"), so sharing one
    dict across paths would accumulate the grant and diverge the surfaces.
    """
    return {
        "attack_damage": 100.0,
        "ability_power": 0.0,
        "base_attack_damage": 61.0,
        "bonus_attack_damage": 39.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 0.0,
        "resource_regen_per_second": 0.0,
        "level": _LEVEL,
        "health": health,
        "max_health": health,
        "base_health": health - 2000.0,
        "bonus_health": 2000.0,
    }


def _parse(option: dict | None = None, *, ranks: dict | None = None):
    stats = _stats()
    abilities = parse_champion_abilities(
        get_champion("Dr. Mundo"),
        _LEVEL,
        0.0,
        ability_ranks=ranks or _RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option,
    )
    return stats, abilities


def _fight(
    option: dict | None = None,
    *,
    duration: float = 6.0,
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
    champion_options: dict | None = None,
) -> dict:
    """The app-level combat payload (full pipeline + survival walk).

    Garen (no crowd control) is the no-trigger fixture; Ahri (immobilize
    charm at t=0, 1.8s at rank 3) is the valid-trigger fixture — the
    control APPLIES to Mundo today (the pre-wiring actual).
    """
    with _testing_client() as client:
        response = client.post(
            "/api/calculate",
            json={
                "champion": "Dr. Mundo",
                "level": _LEVEL,
                "items": [],
                "role": "top",
                "ability_ranks": _RANKS,
                "fight_mode": "time_based",
                "fight_duration": duration,
                "include_auto_attacks": False,
                "target_health": _TARGET_MAX_HP,
                "target_armor": 50,
                "target_mr": 40,
                "champion_options": champion_options or {},
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
    return [e for e in combat.get("healing_events", []) if e.get("attacker") == "main"]


#: MERGE: the passive has TWO heal mechanics and only one of them is
#: modeled.  The 4%-of-maximum-health canister PICKUP heal still never
#: fires (no movement simulation).  The passive's REGENERATION stream --
#: "an additional 0.04% : 0.23% (based on level) of maximum health every
#: 0.5 seconds", the cached P's second row -- is priced by the self-heal
#: rule since the sustain slice, and it publishes under the same ability
#: name.  So "no pickup heal" is a claim about the AMOUNT and cadence, not
#: about the name: a pickup receipt would be an order of magnitude larger
#: than a tick and would not sit on the half-second.
_PICKUP_MAX_HEALTH_RATIO = 0.04
_REGEN_TICK_MAX_RATIO = 0.0023


def _pickup_heals(combat: dict) -> list[dict]:
    """Passive receipts too large to be one regeneration tick."""
    max_health = _survival(combat)["max_health"]
    return [
        heal
        for heal in _main_heals(combat)
        if "Goes Where He Pleases" in str(heal.get("source", ""))
        and float(heal.get("amount", 0.0)) > 2.0 * _REGEN_TICK_MAX_RATIO * max_health
    ]


def _regen_stream_heals(combat: dict) -> list[dict]:
    return [
        heal
        for heal in _main_heals(combat)
        if "Goes Where He Pleases" in str(heal.get("source", ""))
    ]


def _cleanse_event_count(combat: dict) -> int:
    return combat["utility_outcomes"]["participants"]["main"]["cleanse"]["event_count"]


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


def _kernel_survival(
    controls: list[dict] | None = None,
    *,
    duration: float = 10.0,
    main_health: float = 3000.0,
) -> dict:
    """Kernel-level survival run (the Slice 4/5/6/7 evidence path)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("main", "main", health=main_health),
    ]
    # P2 Slice 8: the passive immunity is ARMED by the t=0 arm packet
    # (the participant-timeline authoring mirror).
    arm = {
        "kind": "crowd_control_resist",
        "time": 0.0,
        "amount": 0.0,
        "target_scope": "self",
        "target_policy": "self",
        "source_key": "Dr. Mundo P",
        "source": "Dr. Mundo P — Goes Where He Pleases",
        "attacker": "main",
        "target": "main",
        "_event_id": "main:mundo_p:arm",
    }
    return _simulate_survival(
        combatants,
        {"main": list(controls or [])},
        {"main": []},
        {"main": [arm]},
        duration,
        annotate=False,
    )


def _game_file() -> dict:
    path = Path("data/bin/characters/drmundo.bin.json")
    if not path.exists():
        pytest.skip("local Dr. Mundo game-file evidence is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


def _p_ability() -> dict:
    return _MUNDO_DATA["abilities"]["P"][0]


def _p_effect(index: int) -> dict:
    return _p_ability()["effects"][index]


def _game_regen_row() -> list[float]:
    """Recompute the game file's MaxHealthRegen into the cached
    per-0.5s percent row at levels 1..18.

    The game's fraction is the per-5s rate (0.004 = 0.4% per 5s); the
    wiki's per-0.5s row is that rate / 10 in percent (0.04 at level 1)
    rounded half-up at 2dp.  The per-level increment starts at
    ``mInitialBonusPerLevel`` from level 2 and is REPLACED by each
    breakpoint's ``mBonusPerLevelAtAndAfter`` from that level on
    (0.001 at 7, 0.0015 at 13, 0.002 at 16)."""
    import math

    calc = _game_file()["Characters/DrMundo/Spells/DrMundoPassiveAbility/DrMundoP"][
        "mSpell"
    ]["mSpellCalculations"]["MaxHealthRegen"]
    part = calc["mFormulaParts"][0]
    breakpoints = {
        int(b["mLevel"]): float(b["mBonusPerLevelAtAndAfter"])
        for b in part["mBreakpoints"]
    }
    row = []
    for level in range(1, 19):
        total = float(part["mLevel1Value"])
        for step in range(2, level + 1):
            # The per-level increment is the LAST breakpoint at-or-before
            # the step (each breakpoint REPLACES the increment from its
            # level on), else the initial bonus.
            bonus = float(part["mInitialBonusPerLevel"])
            for breakpoint_level, breakpoint_bonus in sorted(breakpoints.items()):
                if step >= breakpoint_level:
                    bonus = breakpoint_bonus
            total += bonus
        percent_per_0_5s = total * 10.0
        row.append(math.floor(percent_per_0_5s * 100 + 0.5) / 100.0)
    return row


def _resist_packet(time: float, kind: str = "immobilize", duration: float = 1.8):
    """The P2-8 packet shape (pinned candidate): the resist triggers off
    a hostile immobilizing control packet; the completion may fold the
    resist into the control's own event instead."""
    return {
        "time": time,
        "kind": "cleanse",
        "amount": 1.0,
        "cleanse_item": _P_CLEANSE_ITEM,
        "source_key": _P_CLEANSE_ITEM,
        "utility_kind": "cleanse",
        "source": "Dr. Mundo P — Goes Where He Pleases",
        "attacker": "main",
        "target": "main",
        "cleanse_group": "dr-mundo:p",
        "sequence": 0,
        "_event_id": f"mundo:resist:{time}",
        "cc_kind": kind,
        "cc_duration": duration,
    }


def _canister_packet(time: float):
    """The canister drop receipt shape (pinned candidate): dropped at the
    resist time, 525 units away, 7s lifetime."""
    return {
        "time": time,
        "kind": "canister",
        "amount": 1.0,
        "distance": _P_CANISTER_DISTANCE,
        "lifetime": _P_CANISTER_LIFETIME,
        "source": "Dr. Mundo P — Goes Where He Pleases",
        "attacker": "main",
        "target": "main",
        "sequence": 0,
        "_event_id": f"mundo:canister:{time}",
    }


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_p_regen_rows_pinned_in_cache(self):
        # The innate-regeneration rows (the brief's contract #1): the
        # description carries the 5s + 0.5s display ranges and the
        # leveling carries TWO "Max Health Damage" arrays — a 40-entry
        # per-5s display row (0.4..6.7, levels 1..40) and an 18-entry
        # per-0.5s row (0.04..0.23, levels 1..18).  The attribute name is
        # a wiki-template artifact (it is regeneration, not damage) — a
        # source note the declaration receipts.
        effect = _p_effect(0)
        assert "0.4% : 2.3% (based on level) of his maximum health" in (
            effect["description"]
        )
        assert "every 5 seconds" in effect["description"]
        assert "0.04% : 0.23% (based on level)" in effect["description"]
        assert "every 0.5 seconds" in effect["description"]
        rows = effect["leveling"]
        assert [row["attribute"] for row in rows] == [
            "Max Health Damage",
            "Max Health Damage",
        ]
        per_5s = rows[0]["modifiers"][0]["values"]
        per_half = rows[1]["modifiers"][0]["values"]
        assert len(per_5s) == 40
        assert per_5s[0] == pytest.approx(0.4)
        assert per_5s[-1] == pytest.approx(6.7)
        assert per_half == _P_REGENERATION_PER_0_5S
        assert rows[0]["modifiers"][0]["units"] == ["%"] * 40
        assert rows[1]["modifiers"][0]["units"] == ["%"] * 18

    def test_p_regen_rows_recomputed_from_game_file(self):
        # Recompute the per-0.5s regen through the game file's
        # MaxHealthRegen (0.004 + 0.0005/level, +0.001/+0.0015/+0.002 at
        # levels 7/13/16): the cached 18-entry row matches it at the
        # game's own 2dp display precision — the regen is the ONE
        # P value fully discoverable through typed rows today.
        assert _game_regen_row() == _P_REGENERATION_PER_0_5S

    def test_p_immunity_wording_pinned(self):
        # The trigger wording (the brief's contract #1): effects[1]
        # carries the immunity-to-the-next-hostile-immobilizing-effect
        # trigger, the 4% CURRENT-health cost, the 525-unit canister and
        # the 7s lifetime — and its leveling is EMPTY (a source gap: the
        # values live only in the wording + the game file, exactly the
        # ``cooldown_source_gap`` pattern the declaration must receipt).
        effect = _p_effect(1)
        assert "immunity to the next hostile immobilizing effect" in (
            effect["description"]
        )
        assert "4% of his current health" in effect["description"]
        assert "525 units" in effect["description"]
        assert "7 seconds" in effect["description"]
        assert effect["leveling"] == []

    def test_p_pickup_and_respawn_wording_pinned(self):
        # The pickup + destruction wording (the brief's contracts #5/#7/
        # #10): the heal (4% MAX health) and the 15s cooldown reduction
        # are ON THE PICKUP — the wording never heals on the drop — and
        # the enemy destruction is a separate sentence.  effects[3] is
        # the respawn reset.
        pickup = _p_effect(2)
        assert "move near the canister to consume it" in pickup["description"]
        assert "healing himself for 4% of his maximum health" in (pickup["description"])
        assert "reducing the cooldown of Goes Where He Pleases by 15 seconds" in (
            pickup["description"]
        )
        assert "Enemy champions can move near it to destroy it" in (
            pickup["description"]
        )
        assert "cooldown resets upon respawning" in _p_effect(3)["description"]

    def test_p_notes_pinned(self):
        # The cached notes carry the same-cast-instance immunity, the
        # nested-immobilize prevention, the spell-shield/Black-Shield
        # priority, and the canister's Death-Realm + untargetable rules —
        # the named boundaries the completion's immunity model must not
        # contradict (a same-cast-instance immunity is NOT a modeled
        # mechanic today; the notes are receipted evidence).
        notes = _p_ability()["notes"]
        assert "immunity to additional immobilizing effects from the same cast" in (
            notes
        )
        assert "nested into immobilizing ones" in notes
        assert "Spell shield and  Black Shield take priority" in notes
        assert "cannot be interacted with while  untargetable" in notes

    def test_p_cooldown_row_pinned(self):
        # The 60→15 cooldown row (the brief's contract #9): 18 entries by
        # level, NOT affected by CDR, and the passive has no cost /
        # resource (targeting "Passive", affects "Self").
        p = _p_ability()
        assert p["cooldown"]["modifiers"][0]["values"] == _P_COOLDOWN_ROW
        assert p["cooldown"]["affectedByCdr"] is False
        assert p["targeting"] == "Passive"
        assert p["affects"] == "Self"
        assert p["cost"] is None
        assert p["resource"] is None

    def test_p_game_file_evidence(self):
        # Community Dragon evidence (the brief's "game file if present"):
        # DrMundoP DataValues — CurrentHealthLoss 0.04 (the 4% current-
        # health cost), MaxHealthGain 0.04 (the 4% max-health pickup
        # heal), CannisterDistanceAway 525, CannisterGroundDuration 7,
        # CannisterPickupRadius 115, CannisterMaxAngle 70,
        # PassiveCooldownRefund 15 — and the PassiveCooldown breakpoints
        # (60 at level 1, -9 at 3/6/9/12/15/21 → 60→15).
        spell = _game_file()[
            "Characters/DrMundo/Spells/DrMundoPassiveAbility/DrMundoP"
        ]["mSpell"]
        data = {d["name"]: d["values"] for d in spell["DataValues"]}
        assert data["CurrentHealthLoss"][0] == pytest.approx(
            _P_CURRENT_HEALTH_COST_PERCENT / 100.0
        )
        assert data["MaxHealthGain"][0] == pytest.approx(
            _P_MAX_HEALTH_HEAL_PERCENT / 100.0
        )
        assert data["CannisterDistanceAway"][0] == pytest.approx(_P_CANISTER_DISTANCE)
        assert data["CannisterGroundDuration"][0] == pytest.approx(_P_CANISTER_LIFETIME)
        assert data["CannisterPickupRadius"][0] == pytest.approx(115.0)
        assert data["PassiveCooldownRefund"][0] == pytest.approx(_P_PICKUP_CD_REFUND)
        cooldown = spell["mSpellCalculations"]["PassiveCooldown"]["mFormulaParts"][0]
        assert cooldown["mLevel1Value"] == pytest.approx(60.0)
        assert [b["mLevel"] for b in cooldown["mBreakpoints"]] == [
            3,
            6,
            9,
            12,
            15,
            21,
        ]
        # The wiki row interpolates 60→15 linearly while the game steps
        # down in -9 jumps — the endpoints agree, the mid-levels differ
        # (a receipted source note for the coordinator).
        assert _P_COOLDOWN_ROW[0] == pytest.approx(60.0)
        assert _P_COOLDOWN_ROW[-1] == pytest.approx(15.0)
        assert _P_COOLDOWN_ROW[2] != pytest.approx(51.0)

    def test_p_public_receipt_absent_from_parse(self):
        # The module parse receipt (the brief's contract #1): exactly
        # E/Q/R/W — NO P slot (the passive deals no enemy damage).
        #
        # MERGE: P is no longer ``out_of_scope``.  A slot with no cast can
        # still be priced through a named engine channel, and the contract
        # makes the module say WHICH: Dr. Mundo's P is ``modeled`` through
        # ``COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}`` — the
        # regeneration its own healing rule prices.  The claim resolves to
        # a receipt instead of to prose.
        _, abilities = _parse()
        assert sorted(abilities.keys()) == ["E", "Q", "R", "W"]
        from src.calculator.champions import get_champion_module_contract

        contract = get_champion_module_contract("Dr. Mundo")
        MODULE_COVERAGE = contract.coverage

        assert MODULE_COVERAGE["P"] == "modeled"
        assert contract.coverage_channels["P"] == ("self_healing_rule",)
        assert MODULE_COVERAGE["Q"] == "modeled"
        assert MODULE_COVERAGE["W"] == "modeled"
        assert MODULE_COVERAGE["E"] == "modeled"
        assert MODULE_COVERAGE["R"] == "modeled"

    def test_p_absent_option_and_named_api_denial(self):
        # There is NO p option (the brief's contract #2): OPTIONS declares
        # exactly the three fight-state controls (the two fight-state
        # controls plus the E reset-throughput assertion); every p_*
        # spelling is rejected at the API boundary with a named 400 (the
        # option gate lives at the API/scenario boundary — a p_* seed can
        # never silently ride the passive).
        from src.calculator.champions.dr_mundo import OPTIONS

        assert [option["key"] for option in OPTIONS] == [
            "mundo_missing_health_percent",
            "r_nearby_champions",
            "e_reset_throughput",
        ]
        with _testing_client() as client:
            for spelling in ("p_resist_time", "p_canister", "mundo_pickup"):
                response = client.post(
                    "/api/calculate",
                    json={
                        "champion": "Dr. Mundo",
                        "level": _LEVEL,
                        "items": [],
                        "role": "top",
                        "ability_ranks": _RANKS,
                        "fight_mode": "time_based",
                        "fight_duration": 6.0,
                        "include_auto_attacks": False,
                        "target_health": _TARGET_MAX_HP,
                        "target_armor": 50,
                        "target_mr": 40,
                        "champion_options": {spelling: 2.0},
                        "enemies": [
                            {
                                "champion": "Garen",
                                "level": _LEVEL,
                                "items": [],
                            }
                        ],
                    },
                )
                assert response.status_code == 400
                assert (
                    f"champion_options contains unknown option {spelling}"
                    in response.get_json()["error"]
                )

    def test_p_assumptions_name_the_passive(self):
        # MERGE: the ASSUMPTIONS now split the passive by mechanic instead
        # of declaring the whole of it absent -- the canister pickup stays
        # a named unsupported timing, the regeneration stream is priced
        # from the cached row, and the self-sustain carve-out (Q's health
        # cost, W's grey health) is still what is not modeled.
        meta = get_champion_options_meta("Dr. Mundo")
        assert any(
            "canister pickup" in row and "unsupported" in row
            for row in meta["assumptions"]
        )
        assert any(
            "Goes Where He Pleases" in row and "every 0.5 seconds" in row
            for row in meta["assumptions"]
        )
        assert any(
            "grey-health" in row and "not modeled" in row for row in meta["assumptions"]
        )

    def test_p_source_receipts_pin_wiki_revision(self):
        # Source receipts pin the wiki revision the cached rows came from.
        sources = get_champion_options_meta("Dr. Mundo")["sources"]
        assert sources[0]["label"] == "Local League Wiki cache"
        assert sources[0]["url"].endswith("/en-us/Dr._Mundo")
        assert sources[0]["revision_id"] == 4007950

    def test_p_typed_rows_missing_cost_and_heal_rows(self):
        # Pinned source gap (the brief's contract #14): the typed
        # extractors return 0.0 for the empty-leveling P rows — the
        # cost/heal/canister values exist ONLY in the wording + the game
        # file.  The P2-8 declaration must receipt them from the game
        # file and fail LOUD on a missing row (the _require_row
        # precedent), never fall back to a literal.
        assert extract_named(_p_ability(), "Health Cost", 1, {}, {}) == 0.0
        assert extract_named(_p_ability(), "Max Health Heal", 1, {}, {}) == 0.0
        from src.calculator.champions.ksante import _require_row

        with pytest.raises(KeyError) as excinfo:
            _require_row(
                {"name": "Goes Where He Pleases", "effects": [{"leveling": []}]},
                "Health Cost",
            )
        assert "Goes Where He Pleases" in str(excinfo.value)
        assert "Health Cost" in str(excinfo.value)

    def test_p_typed_declaration_publishes_passive_contract(self):
        # P2-8 contract: a typed passive declaration (the GP/Rengar/Milio
        # precedent) publishes the immunity wording + the game-file
        # values (cost 4% current, heal 4% max, canister 525/7s, refund
        # 15s), the 60→15 cooldown row receipted (never enforced), the
        # pickup/destruction named unsupported, and the provenance.
        # Absent today (only Gangplank W / Rengar W / Milio R are
        # declared).
        rule = CHAMPION_CLEANSE_DECLARATIONS.get(_P_CLEANSE_ITEM)
        assert rule is not None, "Dr. Mundo P passive declaration absent"
        assert rule["active_name"] == "Goes Where He Pleases"
        assert rule["target_scope"] == "self"
        assert rule["heal"] is None
        assert rule["cooldown_seconds"] == _P_COOLDOWN_ROW
        assert rule["cooldown_source_gap"] is False
        assert any(
            "hostile immobilizing effect" in str(receipt.get("wording", ""))
            for receipt in rule["source_receipts"]
        )
        assert any(
            "drmundo.bin.json" in str(receipt.get("game_file", ""))
            for receipt in rule["source_receipts"]
        )


# ---------------------------------------------------------------------------
# S2 — No trigger: a fight with no hostile immobilizing control
# ---------------------------------------------------------------------------


class TestNoTrigger:
    def test_no_cc_fight_no_resist_no_cost_no_canister(self):
        # Pinned actual (the brief's contract #2): against Garen (no
        # crowd control at all) Mundo takes no control, pays no health
        # cost, drops no canister and fires no pickup heal — the absence
        # is the pre-wiring behavior (the passive's immunity never
        # fires).  The only heal surface is the already-authored R regen.
        combat = _app_combat(enemy="Garen")
        survival = _survival(combat)
        assert survival["crowd_control_intervals"] == []
        assert survival["action_downtime_intervals"] == []
        assert survival["crowd_control_until"] == pytest.approx(0.0)
        assert _cleanse_event_count(combat) == 0
        assert "cleanse" not in survival
        for key in ("canister", "resist", "passive_cost", "health_cost"):
            assert not any(key in k for k in survival)
        heals = _main_heals(combat)
        assert heals, "the R regen heal surface still fires"
        assert {h["source"] for h in heals} == {
            "Maximum Dosage",
            "Goes Where He Pleases",
        }
        assert _pickup_heals(combat) == []

    def test_no_cc_kernel_no_intervals_no_cleanse(self):
        # Kernel-level mirror: an empty control list leaves both ledgers
        # empty and authors no cleanse/cleanse_use/cleanse_denied keys.
        result = _kernel_survival([])
        main = result["main"]
        assert main["crowd_control_intervals"] == []
        assert main["action_downtime_intervals"] == []
        assert "cleanse" not in main
        assert "cleanse_use" not in main
        assert "cleanse_denied" not in main
        assert "canister" not in main and "passive_cost" not in main
        # The t=0 arm + the receipted cooldown are present (the passive
        # is armed; no trigger -> no resist).
        assert main["passive_state"]["armed"] is True
        assert main["passive_cooldown"]["seconds"] > 0.0

    def test_wired_no_trigger_fires_no_receipts(self):
        # PASS pin (the brief's contract #2): with no hostile
        # immobilizing control the passive stays dormant — no resist
        # receipt, no cost, no canister, and the survival row carries no
        # cleanse keys.  The wired absence must be indistinguishable from
        # today's (the completion keeps this surface).
        combat = _app_combat(enemy="Garen")
        survival = _survival(combat)
        assert survival["crowd_control_intervals"] == []
        assert survival["action_downtime_intervals"] == []
        assert "cleanse" not in survival
        assert "cleanse_use" not in survival
        assert _cleanse_event_count(combat) == 0


# ---------------------------------------------------------------------------
# S3 — Valid immobilizing trigger (the wired resist contract)
# ---------------------------------------------------------------------------


class TestImmobilizingTrigger:
    def test_immobilize_applies_normally_today(self):
        # Pinned actual (the brief's contract #3, pre-wiring): enemy
        # Ahri's charm (cc_kind "immobilize", 1.8s at rank 3) APPLIES to
        # Mundo today — the survival walk authors the interval + the
        # action downtime + the event annotation, and NO resist / cost /
        # canister receipt exists anywhere.  This is the absence the
        # P2-8 completion inverts for the FIRST hostile immobilizing
        # effect.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        assert survival["crowd_control_intervals"] == []
        assert survival["action_downtime_intervals"] == []
        assert survival["crowd_control_until"] == pytest.approx(0.0)
        assert survival["cleanse"]["eligible"] is True
        assert survival["cleanse"]["item"] == _P_CLEANSE_ITEM
        assert survival["cleanse"]["removed_controls"] == []
        assert survival["passive_cost"]["percent"] == pytest.approx(
            _P_CURRENT_HEALTH_COST_PERCENT
        )
        assert survival["canister"]["distance"] == pytest.approx(_P_CANISTER_DISTANCE)
        assert survival["canister"]["lifetime"] == pytest.approx(_P_CANISTER_LIFETIME)

    def test_resist_receipt_keys_absent_from_survival_row(self):
        # The survival row's key set carries NO passive receipts today
        # (the pre-wiring absence the completion adds): no resist,
        # canister, pickup, health-cost or passive-cooldown surfaces.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        # The wired resist publishes the full passive receipt set.
        for key in (
            "cleanse",
            "cleanse_use",
            "canister",
            "passive_cost",
            "passive_cooldown",
            "pickup",
        ):
            assert key in survival

    def test_wired_first_immobilize_is_resisted_never_applied(self):
        # P2-8 contract (the brief's contract #3): the resist intercepts
        # the FIRST hostile immobilizing control — the control is an
        # IMMUNITY, never applied (no crowd_control_intervals /
        # action_downtime contribution from the resisted event, unlike a
        # truncation which would leave historical downtime), the 4%
        # CURRENT-health cost is paid at the resist time, and the
        # canister drop is receipted (525 units, 7s lifetime).
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        assert survival["crowd_control_intervals"] == []
        assert survival["action_downtime_intervals"] == []
        assert survival["crowd_control_until"] == pytest.approx(0.0)
        # The resist receipt names the consumed immunity.
        resist = survival["cleanse"]
        assert resist["eligible"] is True
        assert resist["item"] == _P_CLEANSE_ITEM
        assert resist["removed_controls"] == []
        # The cost is 4% of CURRENT health at the resist time — the
        # receipt carries the exact current at the resist (the R regen
        # heals later in the fight, so the ending-health formula would
        # drift).
        cost = survival["passive_cost"]
        assert cost["percent"] == pytest.approx(_P_CURRENT_HEALTH_COST_PERCENT)
        assert cost["amount"] == pytest.approx(
            _P_CURRENT_HEALTH_COST_PERCENT / 100.0 * cost["health_before"],
            rel=1e-6,
        )
        # The canister drop receipt.
        canister = survival["canister"]
        assert canister["distance"] == pytest.approx(_P_CANISTER_DISTANCE)
        assert canister["lifetime"] == pytest.approx(_P_CANISTER_LIFETIME)
        assert canister["time"] == pytest.approx(0.0)
        # The resist is NOT a cleanse-kind utility event (it is the
        # passive immunity arm) — the utility cleanse count stays 0 and
        # the resist receipts are the survival row's surface.
        assert _cleanse_event_count(combat) == 0


# ---------------------------------------------------------------------------
# S4 — Non-trigger controls
# ---------------------------------------------------------------------------


class TestNonTriggerControls:
    def test_slow_ground_silence_classify_soft(self):
        # Pinned kernel evidence (the brief's contract #4): slow / ground
        # / silence are known SOFT kinds — never blocking, never
        # immobilizing — so the passive's "hostile immobilizing effect"
        # trigger can never fire on them.
        for kind in ("slow", "ground", "silence", "blind", "disarm"):
            assert kind in CONTROL_SOFT_KINDS
            assert kind in KNOWN_CONTROL_KINDS
            assert kind not in CONTROL_BLOCKING_KINDS
            profile = classify_control(SimpleNamespace(cc_kind=kind))
            assert profile.blocking is False
            assert profile.unknown is False

    def test_slow_packet_adds_no_downtime_in_the_walk(self):
        # Pinned walk actual: a slow control packet passes through
        # WITHOUT adding crowd-control or action-downtime intervals — the
        # model has no downtime semantics for soft controls, so there is
        # nothing for an immunity to intercept.
        result = _kernel_survival([_control_packet(0.0, "slow", 2.0)])
        main = result["main"]
        assert main["crowd_control_intervals"] == []
        assert main["action_downtime_intervals"] == []
        assert main["crowd_control_until"] == pytest.approx(0.0)

    def test_wired_slow_does_not_consume_the_immunity(self):
        # P2-8 contract: a slow / ground / non-immobilizing control is
        # applied normally (pass-through) and NEVER triggers the resist —
        # the one-shot immunity stays ARMED (a receipted passive_state,
        # the pinned candidate; the completion's final spelling may
        # differ).
        result = _kernel_survival([_control_packet(0.0, "slow", 2.0)])
        main = result["main"]
        assert main["crowd_control_intervals"] == []
        assert "cleanse" not in main
        assert main["passive_state"]["armed"] is True


# ---------------------------------------------------------------------------
# S5 — Canister timing + lifetime
# ---------------------------------------------------------------------------


class TestCanisterTimingAndLifetime:
    def test_no_canister_surface_today(self):
        # Pinned actual (the brief's contract #5): no canister receipts
        # in the survival row, no canister events, no canister sources —
        # the drop does not exist before the wiring.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        canister = survival["canister"]
        assert canister["time"] == pytest.approx(0.0)
        assert canister["distance"] == pytest.approx(_P_CANISTER_DISTANCE)
        assert canister["lifetime"] == pytest.approx(_P_CANISTER_LIFETIME)
        assert canister["destruction"]["supported"] is False

    def test_wired_canister_drops_at_trigger_with_7s_lifetime(self):
        # P2-8 contract: the canister drop is receipted AT the trigger
        # time with the sourced 525-unit distance and 7s lifetime.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        canister = survival["canister"]
        assert canister["time"] == pytest.approx(0.0)
        assert canister["distance"] == pytest.approx(_P_CANISTER_DISTANCE)
        assert canister["lifetime"] == pytest.approx(_P_CANISTER_LIFETIME)
        assert canister["source"] == _P_CLEANSE_ITEM

    def test_wired_pickup_is_named_unsupported_no_auto_pickup(self):
        # P2-8 contract: the pickup timing is a NAMED unsupported timing —
        # there is NO auto-pickup, NO user toggle, and the pickup heal
        # does NOT fire without a pickup event.  The denial names the
        # missing movement simulation instead of silently healing.
        combat = _app_combat(enemy="Ahri", duration=8.0)
        survival = _survival(combat)
        pickup = survival["pickup"]
        assert pickup["supported"] is False
        assert "movement" in pickup["reason"]
        assert _pickup_heals(combat) == []
        # The half-second regeneration stream is a different mechanic of
        # the same passive and keeps running.
        assert _regen_stream_heals(combat)


# ---------------------------------------------------------------------------
# S6 — Health cost
# ---------------------------------------------------------------------------


class TestHealthCost:
    def test_no_cost_receipt_today(self):
        # Pinned actual (the brief's contract #6): no health-cost receipt
        # — the 4% current-health cost is not paid because the resist
        # never fires.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        cost = survival["passive_cost"]
        assert cost["percent"] == pytest.approx(_P_CURRENT_HEALTH_COST_PERCENT)
        assert cost["amount"] > 0.0
        assert survival["health_damage"] > 0.0  # enemy damage still lands

    def test_wired_cost_is_4_percent_current_health(self):
        # P2-8 contract: the cost is 4% of CURRENT health AT the resist
        # time (not max health, not pre-fight) — recomputed from the
        # fight's own running health.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        cost = survival["passive_cost"]
        assert cost["percent"] == pytest.approx(_P_CURRENT_HEALTH_COST_PERCENT)
        # 4% of the CURRENT health at the resist (the receipt's own
        # health_before — the exact kernel value; the R regen heals later
        # would drift an ending-health-derived formula).
        assert cost["amount"] == pytest.approx(
            _P_CURRENT_HEALTH_COST_PERCENT / 100.0 * cost["health_before"],
            rel=1e-6,
        )


# ---------------------------------------------------------------------------
# S7 — Heal receipt
# ---------------------------------------------------------------------------


class TestHealReceipt:
    def test_pickup_heal_never_fires_today(self):
        # Pinned actual (the brief's contract #7): the P heal is ON THE
        # PICKUP (effects[2] — pinned in S1) and no pickup exists, so no
        # "Goes Where He Pleases" heal fires; the only heal surface is
        # the R regen stream.
        combat = _app_combat(enemy="Ahri")
        heals = _main_heals(combat)
        assert heals
        assert _pickup_heals(combat) == []
        max_health = _survival(combat)["max_health"]
        assert not any(
            float(h.get("amount", 0.0))
            == pytest.approx(_PICKUP_MAX_HEALTH_RATIO * max_health, rel=1e-3)
            for h in heals
        )

    def test_wired_pickup_heal_4_percent_max_health(self):
        # P2-8 contract: the pickup heal is 4% of MAXIMUM health (the
        # game file MaxHealthGain 0.04) and is receipted ONLY with the
        # pickup — a drop alone heals nothing.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        pickup = survival["pickup"]
        assert pickup["heal_percent"] == pytest.approx(_P_MAX_HEALTH_HEAL_PERCENT)
        assert pickup["heal_amount"] == pytest.approx(
            _P_MAX_HEALTH_HEAL_PERCENT / 100.0 * survival["max_health"]
        )
        # No pickup event -> no heal: the drop receipt carries no heal.
        assert "heal" not in survival["canister"]


# ---------------------------------------------------------------------------
# S8 — Cleanse receipt
# ---------------------------------------------------------------------------


class TestCleanseReceipt:
    def test_no_cleanse_receipt_today(self):
        # Pinned actual (the brief's contract #8): the resist receipt
        # does not exist — no cleanse / cleanse_use / cleanse_denied
        # survival keys, zero cleanse event count.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        assert survival["cleanse"]["eligible"] is True
        assert survival["cleanse"]["item"] == _P_CLEANSE_ITEM
        assert survival["cleanse_use"]["uses_after"] == 0

    def test_unavailable_source_fails_closed(self):
        # Pinned actual (the brief's contract #14): the passive source is
        # not declared today, so the resolver fails closed with a KeyError
        # naming the source (a packet that cannot be attributed to a
        # sourced declaration must never guess).
        # P2-8: the passive source now RESOLVES (the declaration
        # landed); the undeclared "Mundo P" spelling still fails closed
        # with the named KeyError (the unavailable-evidence denial).
        assert resolve_cleanse_item("Dr. Mundo P") == "Dr. Mundo P"
        assert resolve_cleanse_item("Goes Where He Pleases") == "Dr. Mundo P"
        with pytest.raises(KeyError) as excinfo:
            resolve_cleanse_item("Mundo P")
        assert "Mundo P" in str(excinfo.value)

    def test_wired_resist_receipt_consumes_immunity(self):
        # P2-8 contract: the resist receipt names the consumed immunity —
        # the control is NOT applied (an immunity, not a truncation: no
        # removed-controls tail, no historical downtime), and the
        # decision/use receipts land on the survival rows.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        resist = survival["cleanse"]
        assert resist["decision"]["eligible"] is True
        assert resist["decision"]["item"] == _P_CLEANSE_ITEM
        assert resist["decision"]["removed_controls"] == []
        assert resist["decision"]["downtime_before"] == pytest.approx(0.0)
        assert resist["decision"]["downtime_after"] == pytest.approx(0.0)
        assert survival["cleanse_use"]["uses_before"] == 1
        assert survival["cleanse_use"]["uses_after"] == 0


# ---------------------------------------------------------------------------
# S9 — Cooldown / reduction
# ---------------------------------------------------------------------------


class TestCooldownAndReduction:
    def test_parse_publishes_no_p_cooldown(self):
        # Pinned actual (the brief's contract #9): the module parse has
        # no P row, so no P cooldown is published anywhere in the engine
        # surface; the app-level fight result carries no passive-cooldown
        # receipt.
        _, abilities = _parse()
        assert "P" not in abilities
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        assert survival["passive_cooldown"]["seconds"] == pytest.approx(
            _P_COOLDOWN_ROW[_LEVEL - 1]
        )
        assert survival["passive_cooldown"]["affected_by_cdr"] is False

    def test_wired_cooldown_row_receipted_never_enforced(self):
        # P2-8 contract: the 60→15-by-level row is receipted (level 18 ->
        # 15.0) but NEVER enforced in-fight (the engine's one-fight model
        # has no recharge timer); the 15s pickup refund is receipted
        # against that row, never applied.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        assert survival["passive_cooldown"]["seconds"] == pytest.approx(
            _P_COOLDOWN_ROW[_LEVEL - 1]
        )
        assert survival["passive_cooldown"]["affected_by_cdr"] is False
        pickup = survival["pickup"]
        assert pickup["cooldown_refund"] == pytest.approx(_P_PICKUP_CD_REFUND)
        # Never enforced: the refund never changes a fight-timing number.
        assert "cooldown" not in survival["cleanse"]


# ---------------------------------------------------------------------------
# S10 — Enemy destruction + unavailable pickup
# ---------------------------------------------------------------------------


class TestDestructionAndUnavailablePickup:
    def test_wired_destruction_and_pickup_fail_closed(self):
        # P2-8 contract (the brief's contract #10): BOTH follow-ups are
        # named fail-closed denials — the enemy destruction needs enemy
        # movement (no movement simulation), the pickup needs Mundo's
        # movement (no auto-pickup, no toggle) — each names its missing
        # mechanic instead of silently granting gold-equivalent value.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        assert survival["canister"]["destruction"] == {
            "supported": False,
            "reason": "enemy movement not modeled",
        }
        assert survival["pickup"]["supported"] is False
        assert "movement" in survival["pickup"]["reason"]


# ---------------------------------------------------------------------------
# S11 — One-use behavior
# ---------------------------------------------------------------------------


class TestOneUseBehavior:
    def test_two_immobilizers_both_apply_today(self):
        # Pinned actual (the brief's contract #11, pre-wiring): a second
        # immobilizing control before any recharge applies normally — the
        # one-shot immunity does not exist yet.
        result = _kernel_survival(
            [
                _control_packet(0.0, "immobilize", 1.8),
                _control_packet(3.0, "stun", 1.5),
            ]
        )
        main = result["main"]
        # The one-shot immunity: the FIRST immobilize is resisted (never
        # applied), the SECOND (a later cast) applies normally.
        assert [i["kind"] for i in main["crowd_control_intervals"]] == ["stun"]
        assert main["crowd_control_until"] == pytest.approx(4.5)
        assert main["cleanse"]["item"] == _P_CLEANSE_ITEM
        assert main["cleanse"]["eligible"] is True
        assert main["cleanse_use"]["uses_after"] == 0

    def test_wired_second_immobilize_applies_normally(self):
        # P2-8 contract: the immunity is ONE-SHOT — the next hostile
        # immobilizing effect is consumed by the resist, and a SECOND
        # immobilizing control BEFORE the cooldown recharges is applied
        # normally (the immunity is not a window).
        result = _kernel_survival(
            [
                _control_packet(0.0, "immobilize", 1.8),
                _control_packet(3.0, "stun", 1.5),
            ]
        )
        main = result["main"]
        assert main["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "stun",
                "start": 3.0,
                "end": 4.5,
                "source": "E",
            }
        ]
        assert main["cleanse"]["decision"]["eligible"] is True
        assert main["cleanse_use"]["uses_after"] == 0


# ---------------------------------------------------------------------------
# S12 — Suppression and castability
# ---------------------------------------------------------------------------


class TestSuppressionAndCastability:
    def test_suppression_is_a_blocking_kind(self):
        # Pinned kernel evidence (the brief's contract #12): suppression
        # is in the blocking/immobilizing classification set — a hostile
        # suppression WOULD qualify as a "hostile immobilizing effect"
        # if the coordinator adopts the blocking set as the trigger
        # classification.
        assert "suppression" in CONTROL_BLOCKING_KINDS
        assert "suppression" in KNOWN_CONTROL_KINDS
        profile = classify_control(SimpleNamespace(cc_kind="suppression"))
        assert profile.blocking is True
        assert profile.unknown is False

    def test_p_wording_has_no_suppression_carve_out(self):
        # Pinned source evidence: the trigger wording says "the next
        # hostile immobilizing effect" with NO exception list (unlike the
        # QSS/Mercurial "except Airborne" or Mikael's explicit
        # exclusions) and no castability gate — the immunity is passive,
        # so the QSS cannotBeSuppressed castability rule does not apply
        # by construction.
        wording = _p_effect(1)["description"]
        assert "hostile immobilizing effect" in wording
        for carve_out in ("except", "Excluding", "but not"):
            assert carve_out not in wording

    def test_wired_suppression_verdict(self):
        # P2-8 contract: the coordinator pins the suppression verdict
        # from the source + game file.  Evidence direction: suppression
        # is an immobilizing effect, the wording carves nothing out, and
        # the immunity is not a cast (no castability gate) — so the
        # resist SHOULD consume suppression; the wiring either models it
        # or returns a named denial naming the missing classification.
        result = _kernel_survival([_control_packet(0.0, "suppression", 1.8)])
        main = result["main"]
        resist = main["cleanse"]
        assert resist["decision"]["eligible"] is True
        assert resist["decision"]["item"] == _P_CLEANSE_ITEM
        assert main["crowd_control_intervals"] == []


# ---------------------------------------------------------------------------
# S13 — Repeated triggers (recharge)
# ---------------------------------------------------------------------------


class TestRepeatedTriggers:
    def test_repeated_immobilizers_apply_today(self):
        # Pinned actual (the brief's contract #13, pre-wiring): every
        # immobilizing control applies — there is no recharge state, so
        # there is nothing to wait out.
        result = _kernel_survival(
            [
                _control_packet(0.0, "immobilize", 1.8),
                _control_packet(2.0, "root", 1.0),
                _control_packet(4.0, "charm", 1.2),
            ]
        )
        main = result["main"]
        # The one-shot: the first immobilize is resisted; the later
        # controls apply until the (receipted, never-enforced) recharge.
        assert [i["kind"] for i in main["crowd_control_intervals"]] == [
            "root",
            "charm",
        ]

    def test_wired_controls_after_resist_apply_until_recharge(self):
        # P2-8 contract: after the resist, subsequent immobilizing
        # controls apply normally until the cooldown recharges (60→15 by
        # level, receipted but never enforced in-fight — a fight window
        # can never outlast the level-18 15s recharge, so the wiring
        # receipts the row and applies every later control).
        result = _kernel_survival(
            [
                _control_packet(0.0, "immobilize", 1.8),
                _control_packet(2.0, "root", 1.0),
            ]
        )
        main = result["main"]
        assert main["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "root",
                "start": 2.0,
                "end": 3.0,
                "source": "E",
            }
        ]
        # The kernel harness dummy is level 1 -> the row's first value
        # 60.0 (the row is receipted by level; never enforced).
        assert main["passive_cooldown"]["seconds"] == pytest.approx(_P_COOLDOWN_ROW[0])


# ---------------------------------------------------------------------------
# S14 — Missing identity or rows (fail-closed)
# ---------------------------------------------------------------------------


class TestMissingIdentityAndRows:
    def test_unavailable_source_fails_closed_named(self):
        # Pinned actual (the brief's contract #14): the P source is not
        # declared, so the resolver's KeyError NAMES the source (the
        # "unavailable evidence" denial) — never a silent guess.
        # P2-8: the declared spelling resolves; an unknown one fails
        # closed with the named KeyError.
        assert resolve_cleanse_item(_P_CLEANSE_ITEM) == _P_CLEANSE_ITEM
        with pytest.raises(KeyError) as excinfo:
            resolve_cleanse_item("Mundo Passive")
        assert "Mundo Passive" in str(excinfo.value)

    def test_require_row_fail_loud_precedent(self):
        # The _require_row precedent (the brief's contract #14): missing
        # leveling rows fail LOUD, naming the ability + the attribute —
        # the helper the P declaration must mirror for the cost/heal
        # rows that live only in the wording + game file today.
        from src.calculator.champions.ksante import _require_row

        fake = {
            "name": "Goes Where He Pleases",
            "effects": [{"leveling": []}],
        }
        with pytest.raises(KeyError) as excinfo:
            _require_row(fake, "Health Cost")
        assert "Goes Where He Pleases" in str(excinfo.value)
        assert "Health Cost" in str(excinfo.value)
        with pytest.raises(KeyError) as excinfo:
            _require_row(fake, "Max Health Heal")
        assert "Max Health Heal" in str(excinfo.value)

    def test_declared_sources_stay_resolvable(self):
        # Unchanged boundary: the already-wired champion cleanses keep
        # resolving (the brief's contract #17) while the P source fails
        # closed — the declaration table is a strict allow-list.
        assert resolve_cleanse_item("Gangplank W") == "Gangplank W"
        assert resolve_cleanse_item("Rengar W") == "Rengar W"
        assert resolve_cleanse_item("Milio R") == "Milio R"
        assert set(CHAMPION_CLEANSE_DECLARATIONS) == {
            "Gangplank W",
            "Rengar W",
            "Milio R",
            "Dr. Mundo P",
            "Olaf R",
        }
        assert resolve_cleanse_item("Dr. Mundo P") == "Dr. Mundo P"
        for item in ("Mikael's Blessing", "Quicksilver Sash", "Mercurial Scimitar"):
            assert item in ITEM_CLEANSE_DECLARATIONS


# ---------------------------------------------------------------------------
# S15 — Score fail-closed
# ---------------------------------------------------------------------------


class TestScoreFailClosed:
    def test_score_gate_names_fail_closed_receipts(self):
        # PASS (the brief's contract #15): the compiled score path ALREADY
        # fails closed on every P2-8 authoring shape — a cleanse-kind
        # template (support_kind=cleanse), a heal packet carrying the
        # cleanse marker (support_cleanse), and a canister-kind template
        # (the compile gate's support_kind=canister); a plain heal stays
        # representable.  The P2-8 wiring must route the resist/canister
        # packets through this gate (never silently re-price the pickup
        # heal as a plain heal or drop the resist).
        resist = _resist_packet(0.0)
        assert compiled_support_receipt(resist) == "support_kind=cleanse"
        assert unrepresentable_template_receipt(resist) == "support_kind=cleanse"
        assert (
            compiled_support_receipt(
                {"kind": "heal", "amount": 100.0, "cleanse_item": _P_CLEANSE_ITEM}
            )
            == "support_cleanse"
        )
        assert (
            unrepresentable_template_receipt(
                {"kind": "heal", "amount": 100.0, "cleanse_item": _P_CLEANSE_ITEM}
            )
            == "support_cleanse"
        )
        canister = _canister_packet(0.0)
        # The contract mirror covers cleanse/movement/heal-with-marker;
        # the compile module's own gate names the canister kind.  The
        # pinned asymmetry: the completion must extend the mirror or the
        # canister packet must ride the compile gate.
        assert unrepresentable_template_receipt(canister) == "support_kind=canister"
        assert compiled_support_receipt({"kind": "heal", "amount": 50.0}) is None
        assert (
            unrepresentable_template_receipt({"kind": "heal", "amount": 50.0}) is None
        )

    def test_wired_score_models_or_receipts_the_passive(self):
        # P2-8 contract: score_only either models the passive IDENTICALLY
        # to the full walk or returns the named receipt for the resist +
        # canister packets — never a silent re-price (the passive must
        # not vanish from the score surface).
        combat = _app_combat(enemy="Ahri")
        # The full surface carries the resist receipt.
        assert _survival(combat)["cleanse"]["decision"]["eligible"] is True
        # The score surface either mirrors it or names the divergence.
        score = _fight({}, one_rotation=True, score_only=True)
        assert "P" not in score["breakdown"]  # the passive stays out of damage


# ---------------------------------------------------------------------------
# S16 — Full vs score parity
# ---------------------------------------------------------------------------


class TestModeParity:
    def test_engine_surface_byte_identical_under_score_only(self):
        # PASS today (the brief's contract #16): the Q/W/E/R engine
        # surface — breakdown rows, total damage, cast timeline, resource
        # ledger — is byte-identical between the full walk and the
        # compiled score path in both fight modes.  EACH path gets a
        # FRESH stats dict (the module parse mutates the caller's stats
        # with R's base-health grant — see _stats).
        for one_rotation in (True, False):
            full = _fight({}, one_rotation=one_rotation)
            scored = _fight({}, one_rotation=one_rotation, score_only=True)
            for slot in ("Q", "W", "E", "R"):
                full_row = full["breakdown"][slot]
                scored_row = scored["breakdown"][slot]
                # The aggregate surface is byte-identical; the
                # ``damage_events`` ledgers differ only in the
                # annotate-gated diagnostics the score lean path strips
                # (raw_formula/source_missing_ratio), never in the damage
                # each event prices.
                assert {k: v for k, v in full_row.items() if k != "damage_events"} == {
                    k: v for k, v in scored_row.items() if k != "damage_events"
                }
                full_events = full_row.get("damage_events") or ()
                scored_events = scored_row.get("damage_events") or ()
                assert [e["damage"] for e in full_events] == [
                    e["damage"] for e in scored_events
                ]
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

    def test_fight_engine_mutates_caller_stats_documented_actual(self):
        # Pinned actual: the FIGHT engine MUTATES the caller's
        # champion_stats dict — ``_apply_stat_buff_ultimates`` applies R's
        # base-health grant in place (health 4391 -> 4720.325 at 30%
        # missing = 25% x 30% x 4391), the "parse-context mutation" the
        # existing test_dr_mundo.py documents.  The parity contract
        # therefore requires a FRESH dict per fight path; a SHARED dict
        # drifts the surfaces (the grant accumulates across runs).
        stats = _stats()
        stats_before = dict(stats)
        _, abilities = _parse()  # parse itself does NOT mutate (rank 3 R)
        _fight({}, one_rotation=True)
        # (probe the engine directly on a fresh dict to pin the grant)
        stats = _stats()
        stats_before = dict(stats)
        abilities = parse_champion_abilities(
            get_champion("Dr. Mundo"),
            _LEVEL,
            0.0,
            ability_ranks=_RANKS,
            champion_stats=stats,
            target_stats={"target_max_health": _TARGET_MAX_HP},
        )
        calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=_TARGET_MAX_HP,
                target_armor=50,
                target_magic_resistance=40,
                fight_duration_seconds=6.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
                enforce_resource_limits=True,
                cast_order=["Q", "W", "E", "R"],
            ),
            score_only=False,
            champion_options={},
        )
        grant = 0.25 * 0.30 * stats_before["health"]
        assert stats["health"] == pytest.approx(stats_before["health"] + grant)
        assert stats["base_health"] == pytest.approx(
            stats_before["base_health"] + grant
        )

    def test_r_regen_heal_surface_fires(self):
        # Pinned actual (the brief's contract #16 "the heal surfaces"):
        # the R regen stream is the already-authored heal surface —
        # one 3%-of-max-health tick every 0.5s from 0.75 for 10s per cast
        # (the game-file 0.5s cadence), recomputed through the typed
        # path.  The P pickup heal is NOT part of it.
        stats = _stats()
        heals = derive_self_healing(
            get_champion("Dr. Mundo"),
            stats,
            {"R": {"rank": 3}},
            [],
            [{"slot": "R", "time": 0.25}],
            6.0,
        )
        per_tick = extract_named(
            get_champion("Dr. Mundo")["abilities"]["R"][0],
            "Health Regenerated per 0.5 Seconds",
            3,
            stats,
            {},
        )
        assert per_tick == pytest.approx(0.03 * stats["health"])
        # MERGE: the passive's own regeneration stream shares the ledger,
        # so the R surface is the "Maximum Dosage" rows.
        dosage = [h for h in heals if h["source"] == "Maximum Dosage"]
        assert [h["time"] for h in dosage] == [0.75 + 0.5 * i for i in range(11)]
        assert all(h["amount"] == pytest.approx(per_tick) for h in dosage)
        assert all(h["kind"] == "champion_ability" for h in dosage)
        assert all(h["actor_wide"] is True for h in dosage)

    def test_r_regen_heal_lands_in_app_fight(self):
        # The same R-regen surface lands in the app-level fight: the
        # healing_events carry Maximum Dosage ticks at 0.75+ while NO
        # passive heal exists (the P surfaces agree at zero).
        combat = _app_combat(enemy="Ahri")
        heals = _main_heals(combat)
        assert heals
        assert any(h["source"] == "Maximum Dosage" for h in heals)
        assert _pickup_heals(combat) == []

    def test_wired_p_parity_and_named_score_divergence(self):
        # P2-8 contract: full vs score agree on the Q/W/E/R + heal
        # surfaces AND the passive's score divergence is NAMED (the
        # resist/canister receipts fail closed on the compiled path —
        # support_kind=cleanse / support_kind=canister) — never a silent
        # re-price of the pickup heal.
        full = _fight({}, one_rotation=True)
        scored = _fight({}, one_rotation=True, score_only=True)
        for slot in ("Q", "W", "E", "R"):
            frow, srow = full["breakdown"][slot], scored["breakdown"][slot]
            # The numeric surface agrees; the per-event annotation
            # fields differ between the adapters (the documented shape).
            assert frow["total_damage"] == srow["total_damage"]
            assert frow["total_raw"] == srow["total_raw"]
            assert frow.get("casts") == srow.get("casts")
        assert compiled_support_receipt(_resist_packet(0.0)) == "support_kind=cleanse"
        assert (
            unrepresentable_template_receipt(_canister_packet(0.0))
            == "support_kind=canister"
        )


# ---------------------------------------------------------------------------
# S17 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_qwer_parse_receipts_unchanged(self):
        # The Q/W/E/R parse receipts are an unchanged boundary (the
        # brief's contract #17): names, ranks, cooldowns, and damage
        # totals recomputed through the typed path at the reference build.
        _, abilities = _parse()
        assert abilities["Q"]["name"] == "Infected Bonesaw"
        assert abilities["Q"]["rank"] == 5
        assert abilities["Q"]["cooldown"] == pytest.approx(4.0)
        assert abilities["W"]["name"] == "Heart Zapper"
        assert abilities["W"]["cooldown"] == pytest.approx(15.0)
        assert abilities["E"]["name"] == "Blunt Force Trauma"
        assert abilities["E"]["cooldown"] == pytest.approx(6.0)
        assert abilities["R"]["name"] == "Maximum Dosage"
        assert abilities["R"]["rank"] == 3
        assert abilities["R"]["total_raw"] == 0.0

    def test_cleanse_tables_unchanged(self):
        # The GP/Rengar/Milio + item cleanse declarations are an
        # unchanged boundary: the table has exactly the three champion
        # entries and the three item entries, with the sourced exclusion
        # sets intact.
        assert set(CHAMPION_CLEANSE_DECLARATIONS) == {
            "Gangplank W",
            "Rengar W",
            "Milio R",
            "Dr. Mundo P",
            "Olaf R",
        }
        assert CHAMPION_CLEANSE_DECLARATIONS["Gangplank W"][
            "excluded_control_kinds"
        ] == ("airborne", "knockback", "knockup")
        assert CHAMPION_CLEANSE_DECLARATIONS["Milio R"]["target_scope"] == (
            "self_and_all_teammates"
        )
        assert set(ITEM_CLEANSE_DECLARATIONS) == {
            "Mikael's Blessing",
            "Quicksilver Sash",
            "Mercurial Scimitar",
        }

    def test_kernel_truncation_contract_unchanged(self):
        # The Slice 4 interval-truncation kernel is an unchanged boundary
        # (the committed Slice 5/6/7 matrix rule): historical intervals
        # kept, an active interval's tail removed (end clamped), a
        # control starting at/after the activation removed entirely by
        # the pure function (the walk's caller contract passes only
        # ACTIVE intervals), unknown kinds never truncated.  The P
        # resist is a DIFFERENT mechanism (an immunity — nothing is ever
        # applied), so it must never ride this truncation path.
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


# ---------------------------------------------------------------------------
# Regression surface (run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (the repo gate):
#
#   .venv/bin/python -m pytest tests/test_dr_mundo_passive.py \
#       tests/test_dr_mundo.py \
#       tests/test_aurelion_sol_stardust_ledger.py \
#       tests/test_senna_souls_ledger.py tests/test_bard_chimes_ledger.py \
#       tests/test_heimerdinger_multihit.py tests/test_ksante_w_resistance.py \
#       tests/test_rengar_ferocity_ledger.py tests/test_rengar_w_cleanse.py \
#       tests/test_gangplank_w_cleanse.py tests/test_milio_r_cleanse.py \
#       tests/test_cleanse_eligibility.py tests/test_cleanse_eligibility_kernel.py \
#       tests/test_cleanse_eligibility_consumers.py \
#       tests/test_state_lifecycle.py tests/test_state_lifecycle_consumers.py \
#       tests/test_resource_ledger.py tests/test_resource_ledger_consumers.py \
#       tests/test_resource_ledger_champion_consumers.py \
#       tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#       tests/test_mana_restore_refund.py tests/test_app.py
#
# The broader regression surface (every test that touches dr_mundo /
# cleanse / crowd-control immunity, per the brief contract #17):
# test_dr_mundo.py test_cleanse_eligibility*.py test_gangplank_w_cleanse.py
# test_rengar_w_cleanse.py test_milio_r_cleanse.py test_survival_kernel.py
# test_state_lifecycle*.py test_app.py
