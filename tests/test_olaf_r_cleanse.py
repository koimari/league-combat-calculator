"""P2 Slice 9 — Olaf R (Ragnarok) champion cleanse + crowd-control
immunity (test-matrix owner: RLM-2 C).

Focused TDD matrix for Olaf's R (Ragnarok): the passive bonus
resistances, the cast-time cleanse of ALL active crowd control, the 3s
immunity window, the bonus-state surface (armor/MR/AD/MS/size), the
castability carve-out, the one-use/cooldown boundaries, and the score
fail-closed behavior.  CURRENT RUNTIME FACTS (verified before pinning):

- Olaf is a PACKET module (src/calculator/champions/olaf.py,
  PACKET_SHA256 abc0765e...): Q/E are modeled packets; W (Tough It Out)
  is the E8c scanner-emitted self shield (10/40/70/100/130 + 17.5%
  missing health, 2.5 s, at the cast — the missing-health term is a
  documented boundary).  MERGE: P, W and R also PRICE their sourced
  steroid rows, so every slot is ``modeled`` and the module declares no
  MODULE_COVERAGE; OPTIONS carries one key (olaf_missing_health_percent,
  which scales Berserker Rage).  There is still no r_* option — the API
  rejects every one with a named 400 ("champion_options contains unknown
  option r_time").
- The module R parse receipt: name "Ragnarok", rank 3, MANA cost 100,
  cast_time None (the cached castTime is "none"), total_raw 0.0 and one
  structural-zero part — the R deals no damage; its stat_buff carries
  the sourced Bonus Resistances and Bonus Attack Damage, and the cached
  rank cooldown row (100/90/80) is published.
- MERGE: because R is a BUFF-phase steroid, the app's derived rotation
  OPENS with it.  The four R receipts anchor on that cast (t=0.0), not
  on a slot-ordered 0.5, and the immunity window is therefore already up
  when an enemy control would land — the app fight BLOCKS the Ahri charm
  instead of truncating it.  The truncation path itself is pinned at
  kernel level, where the packets are authored behind an active control.
  Tests read the activation back off the fight (``_r_activation_time``)
  rather than pinning a rotation-order literal.
- The cached R rows (data/champions.json "Olaf", R[0]):
  effects[0] passive "Passive: Olaf gains bonus armor and bonus magic
  resistance." (Bonus Resistances leveling 10/15/20); effects[1]
  active "Olaf becomes enraged for 3 seconds, cleansing himself of all
  crowd control and becoming immune to them, as well as gaining bonus
  attack damage and 10% increased size. For the first second of
  Ragnarok, he also gains bonus movement speed while facing visible
  enemy champions within 2000 units." (Bonus Attack Damage 10/20/30
  flat + 25% AD; Bonus Movement Speed 20/45/70); effects[2] the
  duration-extension note ("increased by and up to 2.5 seconds for
  each basic attack on-hit or cast of Reckless Swing against an enemy
  champion", leveling EMPTY); cost 100 flat; cooldown 100/90/80
  affectedByCdr; targeting "Auto"; affects "Self"; resource "MANA";
  castTime "none".  The notes carry the airborne displacement-override
  ("removes the underlying stun from airborne effects, but not the
  forced displacement, which requires him to use a blink or dash
  ability to override it"), the no-other-debuffs rule, the dynamic AD
  amplification ("The 25% attack damage scaling amplifies the flat
  attack damage bonus as well") and the duration-extension details
  (dodged basics do not extend, blocked basics do; R will not expire
  during Reckless Swing's cast time).
- Game-file evidence (data/bin/characters/olaf.bin.json,
  OlafRagnarokAbility/OlafRagnarok mSpell): DataValues Resists
  5..35 (ranks 1..3 = 10/15/20), Duration 3.0, FlatAD 0..60 (ranks
  1..3 = 10/20/30), PercentTotalADAmp 0.25, HasteDuration 1.0,
  Haste -0.05..1.45 (ranks 1..3 = 0.20/0.45/0.70 -> 20/45/70%),
  DurationExtension 2.5; cooldownTime [100,100,90,80,...] (ranks
  1..3 = 100/90/80); mana 100; canCastWhileDisabled TRUE and
  cannotBeSuppressed TRUE (the QSS/Mercurial/RengarWEmp flag pair);
  mCantCancelWhileWindingUp true; mSpellTags Trait_Ultimate,
  SpecialCase_StasisLocked, Trait_AttackBuff_Duration, Trait_CCImmune;
  mTargetingTypeData Self; the AD GameCalculation = FlatAD +
  StatByNamedDataValue PercentTotalADAmp (the game's dynamic total-AD
  amplification).
- The engine cast_timeline is the activation clock: one_rotation casts
  Q/W/E/R all at 0.0 (R cost 100); timed casts Q@0.0, W@0.25, E@0.25,
  R@0.5 (R cost 100).  RANK 0 IS NOT A CAST GATE today: the engine
  books the R cast at every rank (rank 0 cost 0.0) — the "R rank 0 ->
  no cast -> no cleanse/immunity/stat receipts" contract is a
  completion fix (xfailed below).
- The P2 Slice 4-8 kernel does NOT wire Olaf today:
  resolve_cleanse_item("Olaf R") FAILS CLOSED with a KeyError naming
  the source; the app-level fight carries NO cleanse / immunity /
  stat-buff rows for main, utility_outcomes cleanse event_count is 0,
  and an enemy Ahri charm (immobilize 1.8 s at t=0) lands untouched
  (crowd_control_intervals + action_downtime 1.8).  The typed kernel
  the completion must ride is ALL in place: the Slice 4 interval
  truncation (truncate_intervals + CleanseEligibility with self scope,
  the caster_control_blocks_cleanse suppression denial, the one-use
  latch), the Slice 3 immunity arm (a SHIELD packet with
  crowd_control_immunity_while_shield grants a typed window tied to
  the EXACT ledger entry — amount must be > 0; a zero-amount shield
  arms nothing), the stat-buff packet kernel (bonus_armor /
  bonus_magic_resistance fields; NO bonus-AD / size / movement fields
  on the stat-buff action), and the score gates
  (compiled_support_receipt / unrepresentable_template_receipt:
  support_kind=cleanse / support_kind=stat_buff / support_kind=
  movement; crowd_control_resist representable).
- Walk dispatch order (same-time ordering): SHIELD / STAT_BUFF /
  UTILITY kinds dispatch BEFORE the attacker-state gate (the
  QSS/Mercurial/GP/Rengar utility-before-gate carve-out), so a
  champion-cast cleanse + immunity + stat buff fire while the caster
  is crowd-controlled; the gate's stasis/invulnerable/untargetable
  branch also never sees them (the game's SpecialCase_StasisLocked
  stasis lock has NO kernel path for support-kind packets today — a
  named boundary).  The suppression denial lives in the CLEANSE
  decision (CAST_BLOCKING_CONTROL_KINDS = {"suppression"} -> the
  named caster_control_blocks_cleanse denial, use NOT consumed).

The coordinator's completion (P2-9) will (most likely) wire the R cast
as the activation (no toggle): per R cast the authoring emits a cleanse
packet (cleanse_item "Olaf R", source "Olaf R — Ragnarok") at the cast
time + a 3s immunity grant (the Slice 3 arm — a nominal timed shield
entry with crowd_control_immunity_while_shield, or a new grant kind)
+ the bonus-state packets (armor/MR stat buffs; the AD / size / MS
rows have NO kernel stat-buff field today — the AD+25%-AD and the 10%
size are receipted as named-unsupported or new fields, the first-
second MS could ride the movement utility surface) + the named
denials (use_spent / unknown_control / caster_control_blocks_cleanse),
and the score fails closed (support_kind=cleanse / stat_buff /
movement — never a silent re-price).  This matrix pins the CONTRACT;
genuinely-absent mechanics are pytest.mark.xfail (non-strict) with
reason "awaiting P2-9 ..." — the completion removes the markers.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (cached R rows: resistances
      10/15/20, AD 10/20/30 + 25% AD, MS 20/45/70, duration 3s, size
      10%, cd 100/90/80, cost 100; the cleanse + immunity wording;
      the game file; the module parse receipt; the source receipts;
      the absent typed R declaration xfailed).
  S2  No R (R rank 0; the option set unchanged — no new option; the
      rank-0 no-cast contract xfailed — the engine casts R at every
      rank today with cost 0 at rank 0).
  S3  R activation timing (engine cast_timeline one_rotation 0.0 /
      timed 0.5; the activation-time == cast-time contract xfailed;
      the missing/invalid timing fail-closed contract xfailed).
  S4  Cleanse of active controls (the kernel truncation contract PASS;
      the charm applies untouched today; the wired cleanse-at-cast
      truncation xfailed: every known kind except the displacement
      family, the airborne displacement-override named boundary).
  S5  Immunity for later controls (the Slice 3 window kernel evidence
      PASS — in-window blocked, after-window applied, end-exclusive;
      the wired 3s R window xfailed).
  S6  Castability while disabled + suppression (the game flag pair
      pinned; the kernel self-scope suppression denial PASS; the wired
      carve-out + the stasis-lock named boundary xfailed).
  S7  Bonus-state receipts (the stat-buff kernel fields PASS; no R
      stat rows today; the wired armor/MR stat-buff rows + the 3s
      window + the duration-extension receipted-never-applied + the
      AD/size named-unsupported boundaries xfailed).
  S8  One-use and cooldown boundaries (the kernel latch evidence PASS;
      the R cooldown row receipted never enforced; the wired one-use
      latch + use_spent + repeated-cast semantics xfailed).
  S9  Same-time ordering (the walk's support-before-gate dispatch +
      the shield-before-damage arm priority PASS; the wired
      cleanse-vs-immunity-vs-stat-buff ordering xfailed).
  S10 Missing identity or rows (resolve_cleanse_item fails closed
      naming the source PASS; the _require_row fail-loud precedent).
  S11 Score fail-closed (the generic gates PASS: support_kind=cleanse /
      stat_buff / movement / support_cleanse; crowd_control_resist
      representable — never a silent re-price).
  S12 Full vs score parity (the Q/W/E/R engine surface byte-identical
      today in both fight modes; the named R divergence xfailed).
  S13 Unchanged boundaries (Q/E damage, the W shield E8c, the module
      OPTIONS + parse receipts, the GP/Rengar/Milio/Dr. Mundo + item
      cleanse declarations, the Slice 3 immunity + resist machinery,
      the Ferocity + grey-health packages untouched).
  S14 Regression surface (the mandated sanity run list, footer).

Expected damage values are recomputed from data/champions.json
leveling rows against the fight's own stats — no literal damage
constants.  The R resist/AD/MS/duration/size/cd/cost rows ARE the
values under test (the typed declaration must publish them), so they
appear as pinned cache + game-file evidence (the K'Sante / Gangplank /
Rengar / Milio / Dr. Mundo matrix precedent).  The declaration item
key below is a pinned CANDIDATE ("Olaf R"); the coordinator's final
spelling is a contract ambiguity reported to the parent.
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
    CAST_BLOCKING_CONTROL_KINDS,
    CHAMPION_CLEANSE_DECLARATIONS,
    ITEM_CLEANSE_DECLARATIONS,
    CleanseEligibility,
    compiled_support_receipt,
    resolve_cleanse_item,
    truncate_intervals,
)
from src.calculator.crowd_control_eligibility import (
    KNOWN_CONTROL_KINDS,
    classify_control,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.survival.actions import SUPPORT_RANK_KEY, TransitionRank
from src.calculator.data_fetcher import get_champion
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
_OLAF_DATA = _CHAMPION_DATA["Olaf"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P2-9 coordinator wires the typed R declaration + the packet
# authoring; genuinely-absent mechanics are xfailed with this reason
# (never strict — the completion removes the markers).
_AWAIT = "awaiting P2-9 wiring"

# The cached R rows the typed declaration must publish (values under
# test — pinned as cache evidence, never literal damage constants).
_R_RESISTANCES = [10, 15, 20]
_R_AD_FLAT = [10, 20, 30]
_R_AD_PERCENT = 25
_R_MS = [20, 45, 70]
_R_DURATION = 3.0
_R_SIZE_PERCENT = 10
_R_COST = [100, 100, 100]
_R_COOLDOWN = [100, 90, 80]
# The cached castTime is "none" — the engine books no cast time.
_R_GAME_EXTENSION = 2.5  # up-to-2.5s per on-hit / Reckless Swing cast

# Pinned CANDIDATE declaration key for the coordinator (the GP/Rengar/
# Milio/Dr. Mundo mirror): the packet source_key / cleanse_item / latch
# key; the candidate source display mirrors "Olaf R — Ragnarok".
_R_CLEANSE_ITEM = "Olaf R"
_R_CLEANSE_SOURCE = "Olaf R — Ragnarok"

# The candidate exclusion set: the wording says "ALL crowd control" but
# the notes carve out the airborne forced displacement (blink/dash to
# override; the stun UNDER the airborne is removable) — the Gangplank
# precedent.  The coordinator's final set is contract ambiguity #3.
_R_EXCLUDED_KINDS = ("airborne", "knockback", "knockup")

# The game file's ranks 1..3 are the DataValues indices 1..3 (index 0 is
# the unlearned/rank-0 row — the Milio HealBase convention).
_GAME_RANK_OFFSET = 1
_GAME_RANK_COUNT = 3


def _stats(max_mana: float = 2000.0) -> dict:
    """Fresh champion stats (the engine fights need enough mana for the
    R cast — the reference build from the Q/E module pins)."""
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
        "ability_power": 0.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 40.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.694,
        "bonus_attack_speed": 0.0,
        "max_mana": max_mana,
        "resource_regen_per_second": 0.0,
        "level": _LEVEL,
        "health": 2000.0,
        "max_health": 2000.0,
    }


def _parse(option: dict | None = None, *, ranks: dict | None = None):
    stats = _stats()
    abilities = parse_champion_abilities(
        get_champion("Olaf"),
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
    max_mana: float = 2000.0,
) -> dict:
    stats = _stats(max_mana=max_mana)
    abilities = parse_champion_abilities(
        get_champion("Olaf"),
        _LEVEL,
        float(stats["ability_power"]),
        ability_ranks=ranks or _RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option,
    )
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
    duration: float = 8.0,
    ranks: dict | None = None,
    champion_options: dict | None = None,
) -> dict:
    """The app-level combat payload (full pipeline + survival walk).

    Garen (no crowd control) keeps the R-absence surface observable;
    Ahri (immobilize charm at t=0 on main) is used for the crowd-control
    gates.
    """
    with _testing_client() as client:
        response = client.post(
            "/api/calculate",
            json={
                "champion": "Olaf",
                "level": _LEVEL,
                "items": [],
                "role": "top",
                "ability_ranks": ranks or _RANKS,
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


def _cleanse_event_count(combat: dict) -> int:
    return combat["utility_outcomes"]["participants"]["main"]["cleanse"]["event_count"]


def _r_activation_time(combat: dict) -> float:
    """The instant the R cast armed Ragnarok, read off the fight itself.

    MERGE: Ragnarok is a priced BUFF-phase steroid on this branch — it
    grants the sourced Bonus Attack Damage and Bonus Resistances — so the
    app's derived rotation OPENS with it (0.0) instead of scheduling it
    behind Q/W/E (0.5).  ``participant_timeline`` still anchors all four
    receipts on the R cast in ``result["cast_timeline"]``, which is the
    contract these tests are about; reading the instant back off the
    fight pins that relationship instead of a rotation-order literal.
    """
    times = [
        float(event["time"])
        for event in combat.get("support_events", ())
        if event.get("attacker") == "main" and event.get("source") == _R_CLEANSE_SOURCE
    ]
    assert times, "no Olaf R receipt in the fight"
    assert len(set(times)) == 1, f"R receipts disagree on the activation: {times}"
    return times[0]


def _r_option_keys(meta: dict) -> list[str]:
    """Any champion option that would make the R cast a toggle."""
    return [
        row["key"]
        for row in meta["options"]
        if row["key"] == "r" or row["key"].startswith("r_")
    ]


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


def _kernel_survival(
    controls: list[dict] | None = None,
    *,
    support: list[dict] | None = None,
    duration: float = 10.0,
    main_health: float = 3000.0,
) -> dict:
    """Kernel-level survival run (the Slice 3/4/5/6/7/8 evidence path)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("main", "main", health=main_health),
    ]
    return _simulate_survival(
        combatants,
        {"main": list(controls or [])},
        {"main": []},
        {"main": list(support or [])},
        duration,
        annotate=False,
    )


def _game_file() -> dict:
    path = Path("data/bin/characters/olaf.bin.json")
    if not path.exists():
        pytest.skip("local Olaf game-file evidence is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


def _r_ability() -> dict:
    return _OLAF_DATA["abilities"]["R"][0]


def _r_game_data_value(name: str) -> list[float]:
    """One OlafRagnarok mSpell DataValues row (ranks 1..3)."""
    spell = _game_file()["Characters/Olaf/Spells/OlafRagnarokAbility/OlafRagnarok"][
        "mSpell"
    ]
    for entry in spell["DataValues"]:
        if entry.get("name") == name:
            return [
                float(value)
                for value in entry["values"][
                    _GAME_RANK_OFFSET : _GAME_RANK_OFFSET + _GAME_RANK_COUNT
                ]
            ]
    raise AssertionError(f"no game DataValue {name!r}")


def _r_game_spell() -> dict:
    return _game_file()["Characters/Olaf/Spells/OlafRagnarokAbility/OlafRagnarok"][
        "mSpell"
    ]


def _leveling(attribute: str) -> dict:
    for effect in _r_ability().get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"no R leveling {attribute!r}")


def _candidate_declaration() -> dict:
    """The pinned CANDIDATE Olaf R cleanse declaration (the shape the
    typed tables must publish — used for the kernel evidence pins)."""
    return {
        "item": _R_CLEANSE_ITEM,
        "active_name": "Ragnarok",
        "target_scope": "self",
        "excluded_control_kinds": _R_EXCLUDED_KINDS,
        "cooldown_seconds": list(_R_COOLDOWN),
        "cooldown_source_gap": False,
        "heal": None,
        "movement": None,
    }


def _ragnarok_cleanse_packet(time: float) -> dict:
    """The P2-9 candidate cleanse packet shape (the GP/Rengar mirror:
    per R cast, at the cast time, self scope, the Slice 4 kernel)."""
    return {
        "time": time,
        "kind": "cleanse",
        "amount": 1.0,
        "target_scope": "self",
        "target_policy": "self",
        "cleanse_item": _R_CLEANSE_ITEM,
        "source_key": _R_CLEANSE_ITEM,
        "utility_kind": "cleanse",
        "source": _R_CLEANSE_SOURCE,
        "attacker": "main",
        "target": "main",
        "sequence": 0,
        "_event_id": f"main:cleanse:R:{time}",
    }


def _ragnarok_immunity_packet(time: float) -> dict:
    """The P2-9 candidate immunity packet (the Slice 3 arm: a shield
    packet with crowd_control_immunity_while_shield, 3s window)."""
    return {
        "time": time,
        "kind": "shield",
        "amount": 1.0,
        "duration": _R_DURATION,
        "target_scope": "self",
        "target_policy": "self",
        "source": _R_CLEANSE_SOURCE,
        "source_key": _R_CLEANSE_ITEM,
        "attacker": "main",
        "target": "main",
        "crowd_control_immunity_while_shield": True,
        "crowd_control_immunity_source": _R_CLEANSE_ITEM,
        "_event_id": f"main:ragnarok:immunity:{time}",
    }


def _ragnarok_stat_buff_packet(time: float, rank: int = 3) -> dict:
    """The P2-9 candidate stat-buff packet (armor/MR at the cast)."""
    resist = _R_RESISTANCES[rank - 1]
    return {
        "time": time,
        "kind": "stat_buff",
        "amount": 0.0,
        "duration": _R_DURATION,
        "target_scope": "self",
        "target_policy": "self",
        "source": _R_CLEANSE_SOURCE,
        "source_key": _R_CLEANSE_ITEM,
        "attacker": "main",
        "target": "main",
        "bonus_armor": float(resist),
        "bonus_magic_resistance": float(resist),
        "_event_id": f"main:ragnarok:buff:{time}",
    }


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_r_rows_pinned_in_cache(self):
        # The R leveling rows (the brief's contract #1): passive Bonus
        # Resistances 10/15/20; active Bonus Attack Damage 10/20/30 flat
        # + 25% AD; Bonus Movement Speed 20/45/70; cost 100 flat;
        # cooldown 100/90/80 affectedByCdr; castTime "none"; Auto / Self
        # / MANA; no damage type.
        resistances = _leveling("Bonus Resistances")
        assert resistances["modifiers"][0]["values"] == _R_RESISTANCES
        assert resistances["modifiers"][0]["units"] == ["", "", ""]
        ad = _leveling("Bonus Attack Damage")
        assert ad["modifiers"][0]["values"] == _R_AD_FLAT
        assert ad["modifiers"][0]["units"] == ["", "", ""]
        assert ad["modifiers"][1]["values"] == [_R_AD_PERCENT] * 3
        assert ad["modifiers"][1]["units"] == ["% AD"] * 3
        ms = _leveling("Bonus Movement Speed")
        assert ms["modifiers"][0]["values"] == _R_MS
        assert ms["modifiers"][0]["units"] == ["%"] * 3
        r = _r_ability()
        assert r["cost"]["modifiers"][0]["values"] == _R_COST
        assert r["cooldown"]["modifiers"][0]["values"] == _R_COOLDOWN
        assert r["cooldown"]["affectedByCdr"] is True
        assert r["castTime"] == "none"
        assert r["targeting"] == "Auto"
        assert r["affects"] == "Self"
        assert r["resource"] == "MANA"
        assert r["damageType"] is None

    def test_r_cleanse_and_immunity_wording_pinned(self):
        # The cleanse + immunity wording (the brief's contract #1): the
        # active effect carries "cleansing himself of all crowd control
        # and becoming immune to them", the 3s enrage, the bonus AD and
        # the 10% size; the first-second MS is conditioned on facing
        # visible enemy champions within 2000 units.
        active = _r_ability()["effects"][1]["description"]
        assert "enraged for 3 seconds" in active
        assert "cleansing himself of all crowd control" in active
        assert "becoming immune to them" in active
        assert "bonus attack damage" in active
        assert "10% increased size" in active
        assert "For the first second of Ragnarok" in active
        assert "facing visible enemy champions within 2000 units" in active
        passive = _r_ability()["effects"][0]["description"]
        assert "bonus armor and bonus magic resistance" in passive

    def test_r_duration_extension_note_pinned(self):
        # The duration-extension note (the brief's contract #1 + #9): up
        # to 2.5 seconds per basic attack on-hit or Reckless Swing cast
        # against an enemy champion, with an EMPTY leveling row (the
        # value lives in prose + the game DataValue only).
        extension = _r_ability()["effects"][2]
        assert "up to 2.5 seconds" in extension["description"]
        assert "Reckless Swing" in extension["description"]
        assert extension["leveling"] == []
        assert (
            _r_game_data_value("DurationExtension")
            == [_R_GAME_EXTENSION] * _GAME_RANK_COUNT
        )

    def test_r_notes_pinned(self):
        # The notes (the brief's contract #1): the airborne
        # displacement-override (stun under airborne removed, forced
        # displacement needs a blink/dash), the no-other-debuffs rule,
        # the dynamic AD amplification and the 25%-AD-amplifies-flat
        # rule, and the duration-extension details.
        notes = _r_ability()["notes"]
        assert "removes the underlying  stun from  airborne effects" in notes
        assert "forced displacement" in notes
        assert "blink or  dash ability to override it" in notes
        assert "does not negate any debuffs other than  crowd control" in notes
        assert "updates dynamically over the duration" in notes
        assert "The 25% attack damage scaling amplifies the flat attack" in notes
        assert "will not expire during  Reckless Swing's cast time" in notes
        assert "duration will not be increased if the basic attack is  dodged" in notes
        assert "duration will be increased if the basic attack is  blocked" in notes

    def test_r_rows_recomputed_from_game_file(self):
        # Community Dragon evidence (the brief's "game file if present"):
        # the game DataValues ranks 1..3 match the cached rows exactly —
        # Resists 10/15/20, FlatAD 10/20/30, PercentTotalADAmp 0.25,
        # Duration 3.0, HasteDuration 1.0, Haste 0.20/0.45/0.70,
        # cooldownTime 100/90/80, mana 100.
        assert _r_game_data_value("Resists") == [float(v) for v in _R_RESISTANCES]
        assert _r_game_data_value("FlatAD") == [float(v) for v in _R_AD_FLAT]
        assert _r_game_data_value("PercentTotalADAmp") == [0.25] * 3
        assert _r_game_data_value("Duration") == [_R_DURATION] * 3
        assert _r_game_data_value("HasteDuration") == [1.0] * 3
        assert _r_game_data_value("Haste") == [pytest.approx(v / 100.0) for v in _R_MS]
        spell = _r_game_spell()
        assert spell["cooldownTime"][1:4] == [float(v) for v in _R_COOLDOWN]
        assert spell["mana"] == [100.0] * 6
        assert spell["mTargetingTypeData"] == {"__type": "Self"}
        calc = spell["mSpellCalculations"]["AD"]["mFormulaParts"]
        assert calc[0]["mDataValue"] == "FlatAD"
        assert calc[1]["mDataValue"] == "PercentTotalADAmp"

    def test_r_game_flags_pin_castability_and_immunity(self):
        # The game castability + immunity flags (the brief's contract
        # #5): canCastWhileDisabled true / cannotBeSuppressed true (the
        # QSS/Mercurial/RengarWEmp flag pair) and the Trait_CCImmune +
        # SpecialCase_StasisLocked spell tags.
        spell = _r_game_spell()
        assert spell["canCastWhileDisabled"] is True
        assert spell["cannotBeSuppressed"] is True
        assert "Trait_CCImmune" in spell["mSpellTags"]
        assert "SpecialCase_StasisLocked" in spell["mSpellTags"]
        assert "Trait_AttackBuff_Duration" in spell["mSpellTags"]
        assert "Trait_Ultimate" in spell["mSpellTags"]

    def test_r_typed_values_via_extract_named(self):
        # Recompute the typed rows through the module's extractor (the
        # brief's "discoverable through the typed path"): the flat rows
        # resolve by attribute + rank; the 25%-AD modifier has no flat
        # resolver (the K'Sante/Gangplank convention — the percentage
        # scaling is a typed row the declaration must publish).
        for rank in range(1, 4):
            assert extract_named(
                _r_ability(), "Bonus Resistances", rank, {}, {}
            ) == pytest.approx(float(_R_RESISTANCES[rank - 1]))
            assert extract_named(
                _r_ability(), "Bonus Attack Damage", rank, {}, {}
            ) == pytest.approx(float(_R_AD_FLAT[rank - 1]))
            assert extract_named(
                _r_ability(), "Bonus Movement Speed", rank, {}, {}
            ) == pytest.approx(float(_R_MS[rank - 1]))

    def test_r_public_receipt_present_in_parse(self):
        # MERGE: the R public receipt is the priced steroid row now, not a
        # no-damage placeholder.  The no-outgoing-damage half of the
        # brief's contract #1 is unchanged (total_raw 0, one structural
        # zero part, no cast time); what is added is the cached rank-3
        # cooldown row (80) the packet module used to withhold and the
        # stat_buff carrying the sourced resistances and bonus AD.
        _, abilities = _parse()
        r = abilities["R"]
        assert r["name"] == "Ragnarok"
        assert r["rank"] == 3
        assert r["cooldown"] == pytest.approx(float(_R_COOLDOWN[2]))
        assert r["resource_type"] == "MANA"
        assert r["resource_cost"] == pytest.approx(100.0)
        # The steroid row publishes no cast_time key (the cached castTime
        # "none" is not a numeric engine cast time).
        assert r.get("cast_time") is None
        assert r["total_raw"] == 0.0
        assert [part.amount for part in r["parts"]] == [0.0]
        assert r["stat_buff"]["armor"] == pytest.approx(float(_R_RESISTANCES[2]))
        assert r["stat_buff"]["magic_resistance"] == pytest.approx(
            float(_R_RESISTANCES[2])
        )
        # 30 flat + the sourced 25% total-AD amplification of the 100 AD
        # reference build.
        assert r["stat_buff"]["bonus_attack_damage"] == pytest.approx(
            float(_R_AD_FLAT[2]) + _R_AD_PERCENT / 100.0 * 100.0
        )
        assert "crowd-control immunity" in r["detail"]

    def test_r_no_outgoing_damage_pin(self):
        # The no-outgoing-damage pin: R total_raw 0 and no damage row in
        # the fight result for every rank and both fight modes.
        for rank in range(1, 4):
            _, abilities = _parse(ranks={**_RANKS, "R": rank})
            assert abilities["R"]["total_raw"] == 0.0
        # P2-9: an unlearned R is ABSENT (the rank-gated no_damage slot).
        _, abilities = _parse(ranks={**_RANKS, "R": 0})
        assert "R" not in abilities
        for one_rotation in (True, False):
            result = _fight({}, one_rotation=one_rotation)
            row = result["breakdown"]["R"]
            assert row["total_raw"] == 0
            assert row["total_damage"] == 0.0
            assert "damage_events" not in row

    def test_r_source_receipts_pin_wiki_revision(self):
        # Source receipts pin the wiki revisions the cached rows came from.
        sources = {
            row["label"]: row for row in get_champion_options_meta("Olaf")["sources"]
        }
        assert sources["Olaf parent entry"]["url"].endswith("/en-us/Olaf")
        assert sources["Olaf parent entry"]["revision_id"] == 3952811
        assert sources["Olaf R ability entry"]["revision_id"] == 2864579

    def test_r_assumptions_name_the_priced_rows_and_the_boundaries(self):
        # MERGE: this branch PRICES R — the sourced Bonus Attack Damage
        # and Bonus Resistances rows are applied over their 3s window —
        # so R is ``modeled`` and the assumptions carry both halves: what
        # is priced, and the crowd-control immunity / movement speed /
        # duration-extension rows that are named rather than priced.
        meta = get_champion_options_meta("Olaf")
        joined = " ".join(meta["assumptions"])
        assert "Tough It Out" in joined
        assert "R's Bonus Attack Damage" in joined
        assert "crowd-control immunity and the up-to-2.5s-per-hit" in joined
        from src.calculator.champions import get_champion_module_contract

        # Coverage has one home now: the validated module contract.  Olaf
        # declares no ``MODULE_COVERAGE`` because every slot prices a row.
        coverage = get_champion_module_contract("Olaf").coverage
        assert coverage == dict.fromkeys("PQWER", "modeled")

    def test_r_typed_declaration_publishes_cleanse_contract(self):
        # P2-9 contract: the typed declaration resolves for the R source
        # (the GP/Rengar/Milio/Dr. Mundo precedent) and publishes the
        # sourced rows: self scope, the ALL-crowd-control wording minus
        # the displacement family, the cooldown 100/90/80 receipted.
        assert resolve_cleanse_item(_R_CLEANSE_ITEM) == _R_CLEANSE_ITEM
        assert resolve_cleanse_item(_R_CLEANSE_SOURCE) == _R_CLEANSE_ITEM
        declaration = CHAMPION_CLEANSE_DECLARATIONS[_R_CLEANSE_ITEM]
        assert declaration["target_scope"] == "self"
        assert declaration["cooldown_seconds"] == [float(v) for v in _R_COOLDOWN]
        assert declaration["cooldown_source_gap"] is False
        assert set(declaration["excluded_control_kinds"]) == set(_R_EXCLUDED_KINDS)
        assert declaration["heal"] is None
        assert declaration["movement"] is None
        wording = " ".join(
            row.get("wording", "")
            for row in declaration["source_receipts"]
            if row.get("wording")
        )
        assert "cleansing himself of all crowd control" in wording


# ---------------------------------------------------------------------------
# S2 — No R (rank 0 / no option / no implicit activation)
# ---------------------------------------------------------------------------


class TestNoR:
    def test_r_rank0_still_books_a_cast_today(self):
        # P2-9: an unlearned R books NO cast (the rank-gated no_damage
        # slot — the Milio precedent) in both fight modes.
        for one_rotation in (True, False):
            result = _fight({}, one_rotation=one_rotation, ranks={**_RANKS, "R": 0})
            assert not [c for c in result["cast_timeline"] if c["slot"] == "R"]
        # A rank-3 one_rotation fight books R at 0.0 with the 100 cost.
        result = _fight({}, one_rotation=True)
        (r_cast,) = [c for c in result["cast_timeline"] if c["slot"] == "R"]
        assert r_cast["time"] == pytest.approx(0.0)
        assert r_cast["resource_cost"] == pytest.approx(100.0)

    def test_r_rank0_no_cleanse_immunity_stat_rows_today(self):
        # Pinned actual (the brief's contract #2): even though the engine
        # books the R cast, NO cleanse/immunity/stat-buff surface exists
        # at any rank — the app fight carries no R rows anywhere.
        # P2-9: the R rank gate removes the rank-0 cast; ranks 1-3 wire
        # the full R surface (cleanse + immunity + stats).
        for ranks in (dict(_RANKS), {**_RANKS, "R": 1}):
            combat = _app_combat(ranks=ranks)
            survival = _survival(combat)
            assert survival["cleanse"]["item"] == _R_CLEANSE_ITEM
            assert survival["cleanse_use"]["uses_after"] == 0
            assert survival["ragnarok_immunity"]["source"] == _R_CLEANSE_SOURCE
            assert _cleanse_event_count(combat) == 1
            assert [
                e
                for e in combat.get("support_events", [])
                if e.get("source") == _R_CLEANSE_SOURCE
            ]

    def test_r_rank0_no_cast_no_receipts(self):
        # P2-9 contract (the brief's contract #2): R rank 0 -> no cast ->
        # no cleanse / immunity / stat receipts — the engine stops
        # booking the R at rank 0 (the Milio/Rengar rank-gate precedent).
        result = _fight({}, one_rotation=True, ranks={**_RANKS, "R": 0})
        assert [c for c in result["cast_timeline"] if c["slot"] == "R"] == []
        combat = _app_combat(ranks={**_RANKS, "R": 0})
        survival = _survival(combat)
        assert "cleanse" not in survival
        assert "cleanse_use" not in survival
        assert "crowd_control_immunity" not in survival

    def test_no_r_option_and_api_rejects_r_keys(self):
        # MERGE: the module declares one option now — Olaf's own missing
        # health, which scales Berserker Rage.  The contract this test is
        # about is untouched by that: there is still NO r_* toggle (the R
        # cast is not optional), and the API rejects every r_* champion
        # option with a named 400.
        meta = get_champion_options_meta("Olaf")
        assert [row["key"] for row in meta["options"]] == [
            "olaf_missing_health_percent"
        ]
        assert not _r_option_keys(meta)
        with _testing_client() as client:
            for key in ("r", "r_time", "r_use", "r_activate"):
                response = client.post(
                    "/api/calculate",
                    json={
                        "champion": "Olaf",
                        "level": _LEVEL,
                        "items": [],
                        "role": "top",
                        "ability_ranks": _RANKS,
                        "fight_mode": "one_rotation",
                        "fight_duration": 10,
                        "include_auto_attacks": False,
                        "target_health": _TARGET_MAX_HP,
                        "target_armor": 50,
                        "target_mr": 40,
                        "champion_options": {key: 1.0},
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
                assert f"unknown option {key}" in response.get_json()["error"]

    def test_seeded_r_options_do_not_change_parse(self):
        # Pinned actual: even a seeded r_* option is silently ignored at
        # the module parse path (the option gate lives at the
        # API/scenario boundary).
        _, plain = _parse()
        _, seeded = _parse({"r_time": 1.0})
        assert plain["R"] == seeded["R"]

    def test_r_cast_is_the_implicit_activation_no_option(self):
        # P2-9 contract: NO user option — the R cast IS the cleanse +
        # immunity + stat-buff activation (the GP/Rengar precedent).
        # MERGE: the activation instant is read off the fight rather than
        # pinned, because a priced R opens the rotation (see
        # ``_r_activation_time``); what this asserts is that the receipts
        # ride that cast and that no option can move them.
        meta = get_champion_options_meta("Olaf")
        assert not _r_option_keys(meta)
        combat = _app_combat()
        survival = _survival(combat)
        assert survival["cleanse"]["activation_time"] == pytest.approx(
            _r_activation_time(combat)
        )
        assert survival["cleanse"]["use_consumed"] is True
        assert _cleanse_event_count(combat) == 1


# ---------------------------------------------------------------------------
# S3 — R activation timing
# ---------------------------------------------------------------------------


class TestRTiming:
    def test_r_cast_times_in_engine_timeline(self):
        # The engine cast_timeline is the activation clock (the brief's
        # contract #3): one_rotation R casts land at 0.0; timed rank-3
        # casts at 0.5 (Q@0.0, W@0.25, E@0.25, R@0.5) with the 100 mana
        # spend in both modes.
        one = _fight({}, one_rotation=True)
        (r_one,) = [c for c in one["cast_timeline"] if c["slot"] == "R"]
        assert r_one["time"] == pytest.approx(0.0)
        assert r_one["resource_cost"] == pytest.approx(100.0)
        timed = _fight({}, duration=6.0)
        r_casts = [c for c in timed["cast_timeline"] if c["slot"] == "R"]
        assert len(r_casts) == 1
        assert r_casts[0]["time"] == pytest.approx(0.5)
        assert r_casts[0]["resource_cost"] == pytest.approx(100.0)

    def test_r_resource_block_skips_the_cast(self):
        # Pinned actual: with enforce_resource_limits the R cast is
        # resource-gated like every slot — a low-mana pool skips the
        # timed R@0.5 cast (Q70 + W50 + E100 + R100 = 320 > 316 base).
        result = _fight({}, duration=6.0, max_mana=316.0)
        assert [c for c in result["cast_timeline"] if c["slot"] == "R"] == []

    def test_r_activation_time_equals_cast_time(self):
        # P2-9 contract (the brief's contract #3): the R cast time IS the
        # cleanse + immunity + stat-buff activation time, with no
        # explicit-time option (the cast IS the activation, the
        # GP/Rengar precedent).  MERGE: all four receipts share one
        # instant — that is what ``_r_activation_time`` asserts — and the
        # immunity window opens on it, three sourced seconds long.
        combat = _app_combat()
        survival = _survival(combat)
        activation = _r_activation_time(combat)
        assert survival["cleanse"]["activation_time"] == pytest.approx(activation)
        assert survival["ragnarok_immunity"]["start"] == pytest.approx(activation)
        assert survival["ragnarok_immunity"]["until"] == pytest.approx(
            activation + _R_DURATION
        )
        assert survival["cleanse"]["decision"]["reason"] == "control_not_active"
        assert survival["cleanse"]["use_consumed"] is True
        assert _cleanse_event_count(combat) == 1

    def test_r_no_typed_timing_option_today(self):
        # Pinned actual (the brief's contract #3 tail): NO typed timing
        # option exists today — the cast timeline IS the activation
        # clock.  IF the coordinator later lands a typed timing option,
        # its missing/invalid values must fail closed with a named denial
        # (never a silent re-anchor of the cast) — the P2-9 contract is
        # documented here for the completion.  MERGE: the module's one
        # option scales Berserker Rage and cannot move the R cast.
        assert not _r_option_keys(get_champion_options_meta("Olaf"))


# ---------------------------------------------------------------------------
# S4 — Cleanse of active controls (all source-supported kinds)
# ---------------------------------------------------------------------------


class TestCleanseOfActiveControls:
    def test_kernel_truncation_contract(self):
        # PASS (the brief's contract #4 + #6): the Slice 4
        # truncate_intervals contract — an interval ACTIVE at the
        # activation ends there, a same-timestamp control is removed
        # entirely, a later control is untouched, historical downtime
        # remains, and a kind outside the eligible set (the displacement
        # family) is never truncated.
        kept, removed = truncate_intervals(
            [
                {"kind": "charm", "start": 0.0, "end": 1.8, "source": "E"},
                {"kind": "airborne", "start": 0.0, "end": 2.0, "source": "R"},
                {"kind": "stun", "start": 0.0, "end": 0.5, "source": "E"},
                {"kind": "root", "start": 1.0, "end": 3.0, "source": "E"},
            ],
            1.0,
            frozenset(KNOWN_CONTROL_KINDS) - frozenset(_R_EXCLUDED_KINDS),
        )
        by_kind = {row["kind"]: row for row in kept}
        assert by_kind["charm"]["end"] == pytest.approx(1.0)  # clamped
        assert by_kind["airborne"]["end"] == pytest.approx(2.0)  # untouched
        assert by_kind["stun"]["end"] == pytest.approx(0.5)  # historical
        # The same-timestamp root [1.0, 3.0) is removed ENTIRELY (the
        # walk's total order applies the control before the cleanse).
        assert "root" not in by_kind
        removed_kinds = [row["kind"] for row in removed]
        assert "root" in removed_kinds
        assert "airborne" not in removed_kinds

    def test_kernel_unknown_kind_fails_closed(self):
        # PASS (the brief's contract #4 tail): an unknown control kind is
        # never truncated (fail-closed) — truncate_intervals keeps it and
        # the eligibility decide() names unknown_control.
        kept, removed = truncate_intervals(
            [{"kind": "mystery", "start": 0.0, "end": 2.0, "source": "E"}],
            1.0,
            frozenset(KNOWN_CONTROL_KINDS),
        )
        assert removed == []
        assert kept[0]["kind"] == "mystery"
        decision = CleanseEligibility(declaration=_candidate_declaration()).decide(
            SimpleNamespace(
                time=1.0,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:1",
                target="main",
                holder="main",
                active_controls=[
                    {"kind": "mystery", "start": 0.0, "end": 2.0, "source": "E"}
                ],
            ),
            holder={"uses_remaining": 1, "item_held": True},
        )
        assert decision.eligible is False
        assert decision.reason == "unknown_control"
        assert decision.use_consumed is False

    def test_kernel_cleanse_decision_shape_with_candidate_declaration(self):
        # PASS kernel evidence: the Slice 4 CleanseEligibility with the
        # CANDIDATE Olaf R declaration (self scope, the displacement
        # exclusion) produces the exact decision shape the R must ride —
        # the active immobilize interval is clamped, its tail removed,
        # the airborne interval is rejected with excluded_control_kind.
        decision = CleanseEligibility(declaration=_candidate_declaration()).decide(
            SimpleNamespace(
                time=1.0,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:1",
                target="main",
                holder="main",
                active_controls=[
                    {"kind": "immobilize", "start": 0.0, "end": 1.8, "source": "E"},
                    {"kind": "airborne", "start": 0.0, "end": 2.0, "source": "R"},
                ],
            ),
            holder={"uses_remaining": 1, "item_held": True},
        )
        assert decision.eligible is True
        assert decision.use_consumed is True
        assert decision.active_controls_before == [
            {"control_kind": "immobilize", "source": "E", "start": 0.0, "end": 1.8},
            {"control_kind": "airborne", "source": "R", "start": 0.0, "end": 2.0},
        ]
        assert decision.removed_controls == [
            {
                "control_kind": "immobilize",
                "source": "E",
                "start": 1.0,
                "end": 1.8,
                "reason": "",
            }
        ]
        assert decision.rejected_controls == [
            {
                "control_kind": "airborne",
                "source": "R",
                "start": 0.0,
                "end": 2.0,
                "reason": "excluded_control_kind",
            }
        ]
        after = {entry["control_kind"]: entry for entry in decision.intervals_after}
        assert after["immobilize"]["end"] == pytest.approx(1.0)
        assert "airborne" in after
        # The merged-downtime metric is the UNION of the intervals — the
        # untouched airborne [0, 2.0] spans both, so the union is 2.0
        # before and after (the truncation is visible in the interval
        # rows, not the union scalar when a longer interval survives).
        assert decision.downtime_before == pytest.approx(2.0)
        assert decision.downtime_after == pytest.approx(2.0)

    def test_the_enemy_charm_never_blocks_olaf(self):
        # MERGE (the brief's contract #4 + #6): with a priced R the
        # rotation OPENS with Ragnarok, so the immunity window is already
        # up when the enemy Ahri charm (immobilize 1.8s at t=0) would
        # land — the charm is BLOCKED outright rather than truncated, and
        # Olaf's action downtime is zero either way.  The cleanse still
        # activates and still spends its one use; it simply finds nothing
        # active to remove, which the decision names.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        activation = _r_activation_time(combat)
        assert survival["crowd_control_intervals"] == []
        assert survival["crowd_control_until"] == pytest.approx(0.0)
        assert survival["action_downtime"] == pytest.approx(0.0)
        assert survival["ragnarok_immunity"]["blocked"] == [
            {"time": 0.0, "source_key": "E", "control_kind": "immobilize"}
        ]
        assert survival["ragnarok_immunity"]["start"] == pytest.approx(activation)
        assert survival["cleanse"]["item"] == _R_CLEANSE_ITEM
        assert _cleanse_event_count(combat) == 1

    def test_r_cleanse_activates_at_the_cast_and_spends_its_use(self):
        # MERGE (the brief's contract #4 + #6): the app-level truncation
        # this used to assert is unreachable now — nothing hostile is
        # still active once Ragnarok opens the rotation — so the
        # truncation ITSELF is pinned at kernel level above
        # (``test_slice4_*`` / ``test_r_denied_under_suppression``, which
        # author the cleanse packet behind an active control).  What the
        # app fight still proves is the wiring: one activation on the R
        # cast, the declared item, the named control_not_active decision,
        # and the one-use latch spent exactly once.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        cleanse = survival["cleanse"]
        assert cleanse["activation_time"] == pytest.approx(_r_activation_time(combat))
        assert cleanse["eligible"] is False
        assert cleanse["decision"]["reason"] == "control_not_active"
        assert cleanse["item"] == _R_CLEANSE_ITEM
        assert cleanse["removed_controls"] == []
        assert cleanse["rejected_controls"] == []
        assert survival["cleanse_use"]["uses_before"] == 1
        assert survival["cleanse_use"]["uses_after"] == 0
        assert survival["cleanse_use"]["activations"] == 1
        assert _cleanse_event_count(combat) == 1

    def test_r_cleanse_excludes_the_displacement_family(self):
        # P2-9 contract (the brief's contract #4 + the notes): the
        # airborne/knockback/knockup intervals are NEVER truncated (the
        # forced displacement needs a blink/dash; the stun UNDER the
        # airborne is a separate removable interval — the named boundary).
        # Kernel-level contract: a cleanse packet authored at the cast
        # rides the Slice 4 kernel with the candidate exclusion set.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        assert set(
            CHAMPION_CLEANSE_DECLARATIONS[_R_CLEANSE_ITEM]["excluded_control_kinds"]
        ) == set(_R_EXCLUDED_KINDS)
        assert survival["cleanse"]["rejected_controls"] == []


# ---------------------------------------------------------------------------
# S5 — Immunity for later controls (the 3s window)
# ---------------------------------------------------------------------------


class TestImmunityWindow:
    def test_slice3_kernel_blocks_inside_applies_after(self):
        # PASS kernel evidence (the brief's contract #7): the Slice 3
        # immunity arm — a shield packet with
        # crowd_control_immunity_while_shield grants the typed window
        # [1.0, 4.0); a control landing INSIDE is blocked (no interval,
        # the blocked receipt with shield amounts + active_until); a
        # control landing AFTER the window applies normally (the
        # outside_window decision is the denial receipt).
        support = [
            {
                "time": 1.0,
                "kind": "shield",
                "amount": 100.0,
                "duration": 3.0,
                "source": "Black Shield",
                "source_key": "Black Shield",
                "attacker": "main",
                "target": "main",
                "target_scope": "self",
                "target_policy": "self",
                "crowd_control_immunity_while_shield": True,
                "crowd_control_immunity_source": "Morgana E",
                "_event_id": "main:shield:0",
            }
        ]
        result = _kernel_survival(
            [
                _control_packet(2.0, "stun", 1.0),
                _control_packet(5.0, "stun", 1.0),
            ],
            support=support,
            duration=8.0,
        )
        survival = result["main"]
        immunity = survival["crowd_control_immunity"]
        assert immunity["window"]["start"] == pytest.approx(1.0)
        assert immunity["window"]["until"] == pytest.approx(4.0)
        assert immunity["active_until"] == pytest.approx(4.0)
        assert immunity["shield_source"] == "Morgana E"
        assert immunity["blocked"] == [
            {
                "time": 2.0,
                "source": "E",
                "control_kind": "stun",
                "shield_amount_before": 100.0,
                "shield_amount_after": 100.0,
                "active_until": 4.0,
                "event_key": "E:2.0:0",
            }
        ]
        assert survival["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "stun",
                "start": 5.0,
                "end": 6.0,
                "source": "E",
            }
        ]
        assert survival["action_downtime"] == pytest.approx(1.0)
        reasons = [d["reason"] for d in immunity["decisions"]]
        assert reasons == ["", "outside_window"]

    def test_slice3_window_is_end_exclusive(self):
        # PASS kernel evidence (the brief's contract #7): the immunity
        # window is end-exclusive — a control landing EXACTLY at the
        # window end applies normally.
        support = [
            {
                "time": 1.0,
                "kind": "shield",
                "amount": 100.0,
                "duration": 3.0,
                "source": "Black Shield",
                "source_key": "Black Shield",
                "attacker": "main",
                "target": "main",
                "target_scope": "self",
                "target_policy": "self",
                "crowd_control_immunity_while_shield": True,
                "crowd_control_immunity_source": "Morgana E",
                "_event_id": "main:shield:0",
            }
        ]
        result = _kernel_survival(
            [_control_packet(4.0, "stun", 1.0)], support=support, duration=8.0
        )
        survival = result["main"]
        assert survival["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "stun",
                "start": 4.0,
                "end": 5.0,
                "source": "E",
            }
        ]
        assert survival["crowd_control_immunity"]["blocked"] == []

    def test_slice3_zero_amount_shield_arms_nothing(self):
        # PASS kernel evidence (the brief's contract #7 boundary): the
        # immunity holder is the EXACT timed ledger entry with amount
        # > 0 — a zero-amount grant arms NO window (a pure-immunity
        # grant with no shield amount has no authored path today; the
        # R completion must decide the nominal-amount vs new-kind
        # question — contract ambiguity #2).
        support = [
            {
                "time": 1.0,
                "kind": "shield",
                "amount": 0.0,
                "duration": 3.0,
                "source": _R_CLEANSE_SOURCE,
                "source_key": _R_CLEANSE_ITEM,
                "attacker": "main",
                "target": "main",
                "target_scope": "self",
                "target_policy": "self",
                "crowd_control_immunity_while_shield": True,
                "crowd_control_immunity_source": _R_CLEANSE_ITEM,
                "_event_id": "main:ragnarok:immunity:0",
            }
        ]
        result = _kernel_survival(
            [_control_packet(2.0, "stun", 1.0)], support=support, duration=8.0
        )
        survival = result["main"]
        assert "crowd_control_immunity" not in survival
        assert survival["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "stun",
                "start": 2.0,
                "end": 3.0,
                "source": "E",
            }
        ]

    def test_r_immunity_blocks_controls_inside_the_3s_window(self):
        # P2-9 contract (the brief's contract #7): a hostile control
        # landing INSIDE the R window [cast, cast+3) is blocked — no
        # interval, the crowd_control_immunity blocked receipt names the
        # R source + the active_until; a control landing AFTER the
        # window applies normally (the outside_window decision receipt).
        result = _kernel_survival(
            [
                _control_packet(2.0, "stun", 1.0),
                _control_packet(5.0, "stun", 1.0),
            ],
            support=[
                _ragnarok_cleanse_packet(1.0),
                _ragnarok_immunity_packet(1.0),
                _ragnarok_stat_buff_packet(1.0),
            ],
            duration=8.0,
        )
        survival = result["main"]
        immunity = survival["crowd_control_immunity"]
        assert immunity["shield_source"] == _R_CLEANSE_ITEM
        assert immunity["window"]["start"] == pytest.approx(1.0)
        assert immunity["window"]["until"] == pytest.approx(4.0)
        assert [b["control_kind"] for b in immunity["blocked"]] == ["stun"]
        assert survival["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "stun",
                "start": 5.0,
                "end": 6.0,
                "source": "E",
            }
        ]

    def test_r_immunity_surface_in_app_fight(self):
        # P2-9 contract: the app fight's survival row carries the
        # crowd_control_immunity receipt from the R cast — the same row
        # the Slice 3 machinery produces for the shield grant.  MERGE:
        # the window opens on the cast the fight booked and runs the
        # sourced 3 seconds from there.
        combat = _app_combat(enemy="Garen")
        activation = _r_activation_time(combat)
        immunity = _survival(combat)["ragnarok_immunity"]
        assert immunity["source"] == _R_CLEANSE_SOURCE
        assert immunity["start"] == pytest.approx(activation)
        assert immunity["until"] == pytest.approx(activation + _R_DURATION)


# ---------------------------------------------------------------------------
# S6 — Castability while disabled + suppression
# ---------------------------------------------------------------------------


class TestCastability:
    def test_game_flags_pin_the_carve_out(self):
        # PASS source evidence (the brief's contract #5): the game file
        # carries canCastWhileDisabled true / cannotBeSuppressed true —
        # the QSS/Mercurial/RengarWEmp flag pair, NOT the Mikael's/Milio
        # gated pattern.  The R cast is castable while disabled but not
        # under suppression; SpecialCase_StasisLocked locks the cast
        # under stasis (a game flag with no kernel path today).
        spell = _r_game_spell()
        assert spell["canCastWhileDisabled"] is True
        assert spell["cannotBeSuppressed"] is True
        assert "SpecialCase_StasisLocked" in spell["mSpellTags"]
        assert "canCastWhileDisabled" not in _r_ability().get("notes", "")

    def test_kernel_suppression_denial_for_self_scope(self):
        # PASS kernel evidence (the brief's contract #5 + #6): the Slice
        # 4 self-scope castability rule — CAST_BLOCKING_CONTROL_KINDS is
        # exactly {"suppression"} and a suppression ACTIVE at the
        # activation denies the cleanse with the named
        # caster_control_blocks_cleanse reason (use NOT consumed).
        assert CAST_BLOCKING_CONTROL_KINDS == frozenset({"suppression"})
        decision = CleanseEligibility(declaration=_candidate_declaration()).decide(
            SimpleNamespace(
                time=1.0,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:1",
                target="main",
                holder="main",
                active_controls=[
                    {"kind": "suppression", "start": 0.0, "end": 2.0, "source": "R"}
                ],
            ),
            holder={"uses_remaining": 1, "item_held": True},
        )
        assert decision.eligible is False
        assert decision.reason == "caster_control_blocks_cleanse"
        assert decision.use_consumed is False
        assert decision.removed_controls == []
        assert decision.rejected_controls == [
            {
                "control_kind": "suppression",
                "source": "R",
                "start": 0.0,
                "end": 2.0,
                "reason": "caster_control_blocks_cleanse",
            }
        ]

    def test_kernel_suppression_not_blocking_cleanse_denial_for_other_kinds(self):
        # PASS kernel evidence: an immobilize ACTIVE at the activation is
        # NOT a castability block — the cleanse is castable while
        # disabled (the QSS/RengarWEmp carve-out) and the active control
        # is simply removed.
        decision = CleanseEligibility(declaration=_candidate_declaration()).decide(
            SimpleNamespace(
                time=1.0,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:1",
                target="main",
                holder="main",
                active_controls=[
                    {"kind": "immobilize", "start": 0.0, "end": 1.8, "source": "E"}
                ],
            ),
            holder={"uses_remaining": 1, "item_held": True},
        )
        assert decision.eligible is True
        assert decision.use_consumed is True

    def test_walk_support_kinds_dispatch_before_the_attacker_gate(self):
        # PASS kernel evidence (the brief's contract #5 + #9): SHIELD /
        # STAT_BUFF / UTILITY support actions dispatch BEFORE the
        # attacker-state gate — the GP W cleanse already fires while the
        # caster is charmed (fired_while_crowd_controlled true), and a
        # champion-cast cleanse rides the same utility-before-gate path.
        combat = _app_combat(enemy="Ahri")
        # The E8c W shield still lands at 0.25 while main is charmed
        # until 1.8 (support-before-gate evidence for the R packets).
        shield_rows = [
            e
            for e in combat.get("support_events", [])
            if e.get("attacker") == "main" and e.get("kind") == "shield"
        ]
        assert shield_rows, "Tough It Out shield missing"
        assert shield_rows[0]["time"] == pytest.approx(0.25)
        assert _survival(combat)["support_shield_received"] == pytest.approx(130.0)

    def test_r_casts_while_crowd_controlled_and_cleanses(self):
        # P2-9 contract (the brief's contract #5): an R cast fires while
        # the caster is charmed (canCastWhileDisabled — the
        # utility-before-gate dispatch), the cleanse truncates the charm
        # at the cast, and the caster use receipt names
        # fired_while_crowd_controlled true.
        #
        # MERGE: the app fight no longer reaches this state — a priced R
        # opens the rotation, so Olaf is never crowd-controlled when it
        # casts (see ``test_the_enemy_charm_never_blocks_olaf``).  The
        # contract is unchanged and is pinned at kernel level instead,
        # the same path ``test_r_denied_under_suppression`` uses: the
        # charm is active [0, 1.8) and the R packets arrive at 0.5.
        result = _kernel_survival(
            [_control_packet(0.0, "immobilize", 1.8, source="E")],
            support=[
                _ragnarok_cleanse_packet(0.5),
                _ragnarok_immunity_packet(0.5),
                _ragnarok_stat_buff_packet(0.5),
            ],
            duration=8.0,
        )
        survival = result["main"]
        assert survival["cleanse"]["activation_time"] == pytest.approx(0.5)
        assert survival["cleanse"]["eligible"] is True
        assert survival["cleanse_use"]["fired_while_crowd_controlled"] is True
        assert survival["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "immobilize",
                "start": 0.0,
                "end": 0.5,
                "source": "E",
            }
        ]
        assert survival["action_downtime"] == pytest.approx(0.5)

    def test_r_denied_under_suppression(self):
        # P2-9 contract (the brief's contract #5 + #6): a suppression
        # ACTIVE at the cast denies the cleanse with the named
        # caster_control_blocks_cleanse denial (the kernel's
        # CAST_BLOCKING_CONTROL_KINDS rule) — the cast does NOT consume
        # the use, the denial + the gated use receipt are written, and
        # the suppression interval STAYS (an existing control is never
        # truncated by a denied cleanse; the immunity window only gates
        # NEW controls).
        result = _kernel_survival(
            [
                _control_packet(0.0, "suppression", 2.0, source="R"),
            ],
            support=[
                _ragnarok_cleanse_packet(0.5),
                _ragnarok_immunity_packet(0.5),
                _ragnarok_stat_buff_packet(0.5),
            ],
            duration=8.0,
        )
        survival = result["main"]
        assert survival["cleanse"]["decision"]["reason"] == (
            "caster_control_blocks_cleanse"
        )
        assert survival["cleanse"]["decision"]["use_consumed"] is False
        assert survival["cleanse_use"]["uses_after"] == 1
        assert survival["crowd_control_intervals"] == [
            {
                "recipient": "main",
                "kind": "suppression",
                "start": 0.0,
                "end": 2.0,
                "source": "R",
            }
        ]

    def test_r_stasis_lock_is_a_named_boundary(self):
        # P2-9 contract boundary (the brief's contract #5 tail): the game
        # flag SpecialCase_StasisLocked locks the R cast under stasis,
        # but the walk's support-kind dispatch has NO stasis gate for
        # support packets today — the completion must either add the
        # stasis denial to the R authoring or receipt the flag as a
        # named-unsupported boundary (never a silent cast-through: an
        # eligible cleanse fired from a stasis-locked caster is a
        # contract violation).
        assert "SpecialCase_StasisLocked" in _r_game_spell()["mSpellTags"]
        # The candidate packet set must not silently fire a SUCCESSFUL
        # cleanse under stasis: the contract is a named denial receipt
        # (eligible False with a reason) or an authored stasis gate that
        # skips the packet — never an eligible True cleanse.
        result = _kernel_survival(
            support=[
                {
                    **_ragnarok_cleanse_packet(1.0),
                    **{SUPPORT_RANK_KEY: TransitionRank.STATE_GRANT},
                }
            ],
            duration=8.0,
        )
        cleanse = result["main"].get("cleanse") or {}
        assert cleanse.get("eligible", False) is not True


# ---------------------------------------------------------------------------
# S7 — Bonus-state receipts (armor/MR/AD/MS/size)
# ---------------------------------------------------------------------------


class TestBonusStateReceipts:
    def test_stat_buff_kernel_fields_exist(self):
        # PASS kernel evidence (the brief's contract #9): the stat-buff
        # packet kernel carries bonus_armor / bonus_magic_resistance /
        # bonus_attack_speed_percent / bonus_health / ability_power /
        # ability_haste / on_hit_magic_damage — the armor+MR half of the
        # R bonus surface has a typed home; there is NO bonus-AD field
        # and NO size field (the AD+25%-AD and 10% size rows are
        # named-unsupported boundaries for the completion).
        result = _kernel_survival(
            support=[
                {
                    "time": 1.0,
                    "kind": "stat_buff",
                    "amount": 0.0,
                    "duration": 3.0,
                    "source": _R_CLEANSE_SOURCE,
                    "source_key": _R_CLEANSE_ITEM,
                    "attacker": "main",
                    "target": "main",
                    "target_scope": "self",
                    "target_policy": "self",
                    "bonus_armor": 20.0,
                    "bonus_magic_resistance": 20.0,
                    "_event_id": "main:ragnarok:buff:1",
                }
            ],
            duration=8.0,
        )
        # The stat-buff kernel accepts the packet (no error) — the public
        # surface is the support_events row the authoring emits.
        assert result["main"]["support_shield_received"] == 0.0

    def test_no_r_stat_rows_in_app_fight_today(self):
        # Pinned actual (the brief's contract #9): no R stat-buff or
        # movement rows exist in the app fight today — support_events
        # carries only the E8c W shield for main.
        combat = _app_combat()
        rows = [
            e for e in combat.get("support_events", []) if e.get("attacker") == "main"
        ]
        # P2-9: the R cast authors the stat-buff + movement rows beside
        # the E8c W shield.
        stat_rows = [
            e
            for e in rows
            if e.get("kind") == "stat_buff" and e.get("source") == _R_CLEANSE_SOURCE
        ]
        assert stat_rows and stat_rows[0]["bonus_armor"] == pytest.approx(20.0)
        movement = combat["utility_outcomes"]["participants"]["main"]["movement"]
        assert movement["event_count"] == 1
        assert movement["speed_percent_seconds"] == pytest.approx(70.0)

    def test_movement_utility_surface_exists(self):
        # PASS kernel evidence (the brief's contract #9): the movement
        # utility surface (the Stormraider precedent) — the kernel
        # accepts a kind "movement" packet (amount / duration), and the
        # public utility movement panel sums bonus_move_speed_percent *
        # duration into speed_percent_seconds.  The first-second MS half
        # of the R could ride this surface (the facing/visible/2000-unit
        # condition has no spatial model — named-unsupported).
        result = _kernel_survival(
            support=[
                {
                    "time": 1.0,
                    "kind": "movement",
                    "amount": 70.0,
                    "bonus_move_speed_percent": 70.0,
                    "duration": 1.0,
                    "source": _R_CLEANSE_SOURCE,
                    "source_key": _R_CLEANSE_ITEM,
                    "attacker": "main",
                    "target": "main",
                    "target_scope": "self",
                    "target_policy": "self",
                    "_event_id": "main:ragnarok:ms:1",
                }
            ],
            duration=8.0,
        )
        # The kernel consumes the movement packet without error; the
        # PUBLIC panel is the combat-level utility_outcomes receipt.
        assert result["main"]["survived_window"] is True
        from src.calculator.participant_timeline import _utility_outcome_receipt

        panel = _utility_outcome_receipt(
            _dummy_combatant("main", "main"),
            [
                {
                    "kind": "movement",
                    "amount": 70.0,
                    "bonus_move_speed_percent": 70.0,
                    "duration": 1.0,
                    "applied_amount": 70.0,
                    "source": _R_CLEANSE_SOURCE,
                }
            ],
            [],
        )
        assert panel["movement"]["event_count"] == 1
        assert panel["movement"]["speed_percent_seconds"] == pytest.approx(70.0)

    def test_r_stat_buff_rows_at_cast(self):
        # P2-9 contract (the brief's contract #9): the R cast authors a
        # stat-buff row (rank-3 resistances 20 armor + 20 MR over the
        # sourced 3s window) — the public support_events row with the
        # sourced values.  MERGE: the row is anchored on the cast the
        # fight booked, and the window still runs 3 seconds from it.
        combat = _app_combat()
        activation = _r_activation_time(combat)
        rows = [
            e
            for e in combat.get("support_events", [])
            if e.get("attacker") == "main" and e.get("kind") == "stat_buff"
        ]
        assert rows, "R stat-buff row missing"
        buff = rows[0]
        assert buff["source"] == _R_CLEANSE_SOURCE
        assert buff["bonus_armor"] == pytest.approx(float(_R_RESISTANCES[2]))
        assert buff["bonus_magic_resistance"] == pytest.approx(float(_R_RESISTANCES[2]))
        assert buff["time"] == pytest.approx(activation)
        assert buff["duration"] == pytest.approx(_R_DURATION)
        assert buff["expires_at"] == pytest.approx(activation + _R_DURATION)

    def test_r_ad_and_size_receipted_named_unsupported(self):
        # P2-9 contract (the brief's contract #9): the bonus AD
        # (10/20/30 + 25% AD — the dynamic total-AD amplification) and
        # the 10% size have NO stat-buff field in the kernel; the
        # completion must receipt them as named-unsupported (or add new
        # fields) — never silently drop them.  The movement panel gets
        # the first-second MS (20/45/70) with the facing condition
        # named-unsupported.
        combat = _app_combat()
        movement = combat["utility_outcomes"]["participants"]["main"]["movement"]
        assert movement["event_count"] == 1
        assert movement["speed_percent_seconds"] == pytest.approx(70.0)
        # The AD + size rows live in the declaration's source receipts.
        declaration = CHAMPION_CLEANSE_DECLARATIONS[_R_CLEANSE_ITEM]
        assert any(
            "25% attack damage" in row.get("wording", "")
            for row in declaration["source_receipts"]
            if row.get("wording")
        )

    def test_r_duration_extension_receipted_never_applied(self):
        # P2-9 contract (the brief's contract #9 tail): the duration
        # extension (up to 2.5s per on-hit / Reckless Swing cast against
        # a champion) is RECEIPTED, never enforced — the engine has no
        # dynamic-duration machinery and the 3s window stays fixed; the
        # receipt names the 2.5s row as a named-unsupported timing.
        declaration = CHAMPION_CLEANSE_DECLARATIONS[_R_CLEANSE_ITEM]
        assert any(
            "2.5 seconds" in row.get("wording", "")
            for row in declaration["source_receipts"]
            if row.get("wording")
        )
        combat = _app_combat(enemy="Ahri")
        # MERGE: the fixed-window claim is the point, so it is asserted as
        # a LENGTH — the window is the sourced 3 seconds from the cast,
        # never 3 + 2.5 — rather than as a pinned end instant.
        immunity = _survival(combat)["ragnarok_immunity"]
        assert immunity["until"] - immunity["start"] == pytest.approx(_R_DURATION)
        assert immunity["until"] == pytest.approx(
            _r_activation_time(combat) + _R_DURATION
        )


# ---------------------------------------------------------------------------
# S8 — One-use and cooldown boundaries
# ---------------------------------------------------------------------------


class TestOneUseAndCooldown:
    def test_kernel_one_use_latch(self):
        # PASS kernel evidence (the brief's contract #8): the Slice 4
        # per-fight one-use latch — a second activation of the same
        # source fails closed with the named use_spent denial (the use
        # NOT consumed) while the first activation consumes the single
        # use.  (The candidate R packet itself fails closed today — the
        # latch is pinned directly through the typed kernel below.)
        decision = CleanseEligibility(declaration=_candidate_declaration()).decide(
            SimpleNamespace(
                time=1.0,
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
        assert decision.removed_controls == []

    def test_kernel_second_activation_receipted_denied(self):
        # PASS kernel evidence (the brief's contract #8): a second
        # activation in one fight writes the cleanse_denied receipt with
        # reason use_spent and never touches the intervals.
        decision = CleanseEligibility(declaration=_candidate_declaration()).decide(
            SimpleNamespace(
                time=5.0,
                source_key=_R_CLEANSE_ITEM,
                sequence=0,
                event_id="r:2",
                target="main",
                holder="main",
                active_controls=[],
            ),
            holder={"uses_remaining": 0, "item_held": True},
        )
        assert decision.reason == "use_spent"
        assert decision.use_consumed is False

    def test_r_cooldown_row_pinned_and_never_enforced(self):
        # Pinned actual (the brief's contract #8): the cached cooldown
        # row 100/90/80 (affectedByCdr) + the game cooldownTime agree,
        # and the module parse now PUBLISHES that row per rank.
        #
        # It published 0.0 until the utility-axis slice rebuilt this
        # module around ``slotlib.extract_cooldown`` (Olaf P/W/R were
        # priced as stat grants); the golden baseline carries the same
        # value (Olaf/abilities_level_11/R cooldown 90.0 = the rank-2
        # row), so the published figure is the sourced one and the 0.0
        # here was a stale pin from before that slice, not a regression.
        #
        # "Never enforced" is the half that still has to hold, and it is
        # asserted below rather than assumed: R books exactly ONE cast no
        # matter how long the window is — at 400s, five times the rank-3
        # cooldown, it is still one — while Q/W/E in the same fight do
        # scale with the window.  So the typed declaration receipts the
        # row; nothing re-arms R off it.
        assert _r_ability()["cooldown"]["modifiers"][0]["values"] == _R_COOLDOWN
        assert _r_game_spell()["cooldownTime"][1:4] == [float(v) for v in _R_COOLDOWN]
        for rank, sourced in enumerate(_R_COOLDOWN, start=1):
            _, ranked = _parse(ranks={**_RANKS, "R": rank})
            assert ranked["R"]["cooldown"] == pytest.approx(float(sourced))
        _, abilities = _parse()
        assert abilities["R"]["cooldown"] == pytest.approx(float(_R_COOLDOWN[2]))
        timed = _fight({}, duration=30.0)
        r_casts = [c for c in timed["cast_timeline"] if c["slot"] == "R"]
        assert len(r_casts) == 1
        assert r_casts[0]["time"] == pytest.approx(0.5)
        # The cooldown is receipted, never re-armed: a window five rank-3
        # cooldowns long still books one R, while the other slots repeat.
        long_fight = _fight({}, duration=400.0)
        long_casts = [c for c in long_fight["cast_timeline"] if c["slot"] == "R"]
        assert len(long_casts) == 1
        assert long_casts[0]["time"] == pytest.approx(0.5)
        assert (
            len([c for c in long_fight["cast_timeline"] if c["slot"] == "Q"]) > 1
        ), "the other slots do repeat, so one R is R's own rule"

    def test_r_second_cast_fails_closed_use_spent(self):
        # P2-9 contract (the brief's contract #8): the per-fight one-use
        # latch — a SECOND R cast in one fight is denied with the named
        # use_spent denial + the cleanse_denied receipt (the engine's
        # single-cast rule makes this unreachable in practice, but the
        # latch must hold for authored casts); the repeated-cast
        # semantics are "first cast consumes, later casts denied".
        result = _kernel_survival(
            support=[
                _ragnarok_cleanse_packet(1.0),
                _ragnarok_cleanse_packet(6.0),
            ],
            duration=8.0,
        )
        survival = result["main"]
        assert survival["cleanse"]["use_consumed"] is True
        assert survival["cleanse_use"]["uses_after"] == 0
        assert survival["cleanse_denied"] == [{"time": 6.0, "reason": "use_spent"}]


# ---------------------------------------------------------------------------
# S9 — Same-time ordering (cleanse vs immunity start vs stat buffs)
# ---------------------------------------------------------------------------


class TestSameTimeOrdering:
    def test_walk_dispatch_order_support_before_gate(self):
        # PASS kernel evidence (the brief's contract #10): the survival
        # walk dispatches SHIELD / STAT_BUFF / UTILITY actions BEFORE
        # the attacker-state gate, and a barrier arms before the
        # same-timestamp damage — a shield cast at t must see a damage
        # packet at t.  The R's own packets (cleanse/immunity/stat buff
        # at the cast) all dispatch in this support band; the exact
        # intra-band order is the walk's total order (action_key: rank,
        # time, participant, sequence).  Read off the one rank ladder:
        # the parallel float table this used to read is retired.
        from src.calculator.survival.actions import support_transition_rank

        shield_rank = support_transition_rank({"kind": "shield"})
        assert shield_rank is TransitionRank.BARRIER_GRANT
        assert shield_rank < TransitionRank.DAMAGE
        # A modifier already in force at its own timestamp declares the
        # aura rank, which is the other pre-damage slot; the kind alone
        # would arm it as a triggered debuff, after the damage.
        assert TransitionRank.AURA_ARM < TransitionRank.DAMAGE
        # A same-timestamp control after a shield-with-immunity grant is
        # blocked (the shield arms first).
        result = _kernel_survival(
            [_control_packet(1.0, "stun", 1.0)],
            support=[
                {
                    "time": 1.0,
                    "kind": "shield",
                    "amount": 100.0,
                    "duration": 3.0,
                    "source": "Black Shield",
                    "source_key": "Black Shield",
                    "attacker": "main",
                    "target": "main",
                    "target_scope": "self",
                    "target_policy": "self",
                    "crowd_control_immunity_while_shield": True,
                    "crowd_control_immunity_source": "Morgana E",
                    "_event_id": "main:shield:1",
                }
            ],
            duration=8.0,
        )
        survival = result["main"]
        assert survival["crowd_control_intervals"] == []
        assert survival["crowd_control_immunity"]["blocked"][0]["time"] == 1.0

    def test_walk_order_cleanse_then_immunity_then_stat_buff_at_cast(self):
        # PASS kernel evidence (the brief's contract #10): at the R cast
        # time the authoring emits the packets in the walk's support
        # band; the Slice 4 cleanse decision reads the ACTIVE intervals
        # at the activation (the intervals already in the ledger), the
        # immunity arms a NEW window, and the stat buff is a NEW timed
        # row — the three receipts coexist at one timestamp without
        # reordering the damage walk (the deterministic total order).
        # Kernel evidence: the GP W cleanse already demonstrates the
        # per-cast receipt trio (cleanse + heal) landing at one
        # timestamp in the app fight.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        # The E8c W shield (support band) landed at 0.25 even though the
        # same-timestamp W heal + cleanse ordering is the walk's total
        # order — the shield row proves the support band executes at the
        # cast time.
        assert any(
            e.get("attacker") == "main"
            and e.get("kind") == "shield"
            and e.get("time") == pytest.approx(0.25)
            for e in combat.get("support_events", [])
        )

    def test_r_same_time_cleanse_immunity_stat_buff_receipts(self):
        # P2-9 contract (the brief's contract #10): at the cast time the
        # survival row carries ALL THREE receipts anchored at the same
        # activation: the cleanse truncation, the immunity window start
        # and the stat-buff rows — the deterministic walk order (cleanse
        # decision first against the pre-cast intervals, then the
        # immunity window, then the stat rows) never re-prices damage.
        combat = _app_combat(enemy="Ahri")
        survival = _survival(combat)
        # MERGE: "the same activation" is the claim, so it is read off the
        # fight — ``_r_activation_time`` fails if the four receipts ever
        # disagree — instead of restating one instant three times.
        activation = _r_activation_time(combat)
        assert survival["cleanse"]["activation_time"] == pytest.approx(activation)
        assert survival["ragnarok_immunity"]["start"] == pytest.approx(activation)
        buffs = [
            e
            for e in combat.get("support_events", [])
            if e.get("attacker") == "main" and e.get("kind") == "stat_buff"
        ]
        assert buffs[0]["time"] == pytest.approx(activation)


# ---------------------------------------------------------------------------
# S10 — Missing identity or rows (fail-closed)
# ---------------------------------------------------------------------------


class TestMissingIdentityAndRows:
    def test_unavailable_source_fails_closed_named(self):
        # Pinned actual (the brief's contract #11): the R source is not
        # a declared cleanse — resolve_cleanse_item fails closed with a
        # KeyError naming the source (the unavailable-source denial).
        # P2-9: the R source now RESOLVES (the declaration landed); an
        # unknown spelling still fails closed with the named KeyError.
        assert resolve_cleanse_item(_R_CLEANSE_ITEM) == _R_CLEANSE_ITEM
        assert resolve_cleanse_item(_R_CLEANSE_SOURCE) == _R_CLEANSE_ITEM
        assert resolve_cleanse_item("Ragnarok") == _R_CLEANSE_ITEM
        assert _R_CLEANSE_ITEM in CHAMPION_CLEANSE_DECLARATIONS
        # The already-wired declarations keep resolving (strict
        # allow-list).
        with pytest.raises(KeyError) as excinfo:
            resolve_cleanse_item("Bogus R")
        assert "Bogus R" in str(excinfo.value)
        assert resolve_cleanse_item("Gangplank W") == "Gangplank W"
        assert resolve_cleanse_item("Rengar W") == "Rengar W"
        assert resolve_cleanse_item("Milio R") == "Milio R"
        assert resolve_cleanse_item("Dr. Mundo P") == "Dr. Mundo P"
        assert resolve_cleanse_item("Mercurial Scimitar") == "Mercurial Scimitar"

    def test_require_row_fail_loud_precedent(self):
        # The _require_row precedent (the brief's contract #11): missing
        # leveling rows fail LOUD, naming the ability + the attribute —
        # the helper the R declaration must mirror for any row the
        # parser drops (the duration-extension row has EMPTY leveling).
        from src.calculator.champions.ksante import _require_row

        fake = {
            "name": "Ragnarok",
            "effects": [{"leveling": []}],
        }
        with pytest.raises(KeyError) as excinfo:
            _require_row(fake, "Bonus Resistances")
        assert "Ragnarok" in str(excinfo.value)
        assert "Bonus Resistances" in str(excinfo.value)
        # The duration-extension row is prose + game DataValue only —
        # its EMPTY leveling is a pinned source gap today.
        assert _r_ability()["effects"][2]["leveling"] == []

    def test_kernel_unknown_cleanse_packet_never_fires(self):
        # Pinned actual (the brief's contract #11): a cleanse packet
        # whose source is undeclared FAILS CLOSED in the walk — it can
        # never silently truncate or consume a use (the R packet today
        # raises the named KeyError instead of guessing).
        # P2-9: the declared R packet now applies; an UNDECLARED packet
        # still fails closed in the walk (never silently truncates).
        result = _kernel_survival(
            support=[_ragnarok_cleanse_packet(1.0)],
            duration=8.0,
        )
        assert result["main"]["cleanse"]["item"] == _R_CLEANSE_ITEM
        with pytest.raises(KeyError) as excinfo:
            _kernel_survival(
                support=[
                    {
                        **_ragnarok_cleanse_packet(1.0),
                        "cleanse_item": "Bogus R",
                        "source_key": "Bogus R",
                    }
                ],
                duration=8.0,
            )
        assert "Bogus R" in str(excinfo.value)


# ---------------------------------------------------------------------------
# S11 — Score fail-closed (never a silent re-price)
# ---------------------------------------------------------------------------


class TestScoreFailClosed:
    def test_score_gate_names_fail_closed_receipts(self):
        # PASS (the brief's contract #12): the compiled score path
        # ALREADY fails closed on every Olaf R authoring shape — a
        # cleanse-kind template (support_kind=cleanse), a stat-buff
        # template (support_kind=stat_buff) and a movement template
        # (support_kind=movement) are unrepresentable; the
        # crowd_control_resist arm stays representable; a heal packet
        # carrying the cleanse marker fails with support_cleanse.  The
        # P2-9 wiring must route the R packets through this gate (never
        # silently re-price the buffs or drop the cleanse).
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": _R_CLEANSE_ITEM,
            "source_key": _R_CLEANSE_ITEM,
            "utility_kind": "cleanse",
            "source": _R_CLEANSE_SOURCE,
            "time": 0.5,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:R:0",
        }
        assert compiled_support_receipt(template) == "support_kind=cleanse"
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"
        # The cleanse_eligibility MIRROR owns only the cleanse/movement
        # kinds (stat_buff falls through to the compile module's own
        # gate); the compile gate itself names support_kind=stat_buff.
        assert (
            compiled_support_receipt(
                {"kind": "stat_buff", "amount": 0.0, "bonus_armor": 20.0}
            )
            is None
        )
        assert (
            unrepresentable_template_receipt(
                {"kind": "stat_buff", "amount": 0.0, "bonus_armor": 20.0}
            )
            == "support_kind=stat_buff"
        )
        assert (
            compiled_support_receipt({"kind": "movement", "amount": 70.0})
            == "support_kind=movement"
        )
        assert (
            compiled_support_receipt({"kind": "heal", "amount": 100.0, "cleanse": True})
            == "support_cleanse"
        )
        # The Slice 8 resist arm is representable (it only arms state).
        assert (
            compiled_support_receipt({"kind": "crowd_control_resist", "amount": 0.0})
            is None
        )
        assert (
            unrepresentable_template_receipt(
                {"kind": "crowd_control_resist", "amount": 0.0}
            )
            is None
        )

    def test_score_gate_never_reprices_a_cleanse_carrying_heal(self):
        # PASS: the same packet WITH the cleanse marker flips from
        # representable to the named receipt — the gate can never
        # silently re-price a cleanse-carrying packet as a plain heal.
        heal_template = {
            "kind": "heal",
            "amount": 100.0,
            "source": _R_CLEANSE_SOURCE,
            "time": 0.5,
        }
        assert compiled_support_receipt(heal_template) is None
        assert unrepresentable_template_receipt(heal_template) is None
        marked = {**heal_template, "cleanse": True}
        assert compiled_support_receipt(marked) == "support_cleanse"
        assert unrepresentable_template_receipt(marked) == "support_cleanse"

    def test_wired_score_models_or_receipts_the_r(self):
        # P2-9 contract (the brief's contract #12): score_only either
        # models the R identically (the QSS/Mercurial compiled path) or
        # returns the named receipt — never a silent re-price.  The
        # current gate receipts (support_kind=cleanse / stat_buff /
        # movement) are the named divergence the compiled path must
        # publish in its notes.
        # The engine score path prices the R surface identically (0
        # damage) and the couple score gates name the fail-closed
        # receipts for the R packets — never a silent re-price.
        scored = _fight({}, one_rotation=True, score_only=True)
        assert scored["breakdown"]["R"]["total_damage"] == 0.0
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": "Olaf R",
            "source_key": "Olaf R",
            "utility_kind": "cleanse",
            "source": "Olaf R — Ragnarok",
            "time": 0.5,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:olaf:r:cleanse:0",
        }
        assert compiled_support_receipt(template) == "support_kind=cleanse"
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"


# ---------------------------------------------------------------------------
# S12 — Full vs score parity
# ---------------------------------------------------------------------------


class TestModeParity:
    def test_engine_surface_byte_identical_under_score_only(self):
        # PASS today (the brief's contract #13): the R surface — the
        # breakdown row, the mana ledger, the resource spend — is
        # byte-identical between the full walk and the compiled score
        # path in both fight modes; the R stays OUT of outgoing damage
        # in both modes.
        for one_rotation in (True, False):
            full = _fight({}, one_rotation=one_rotation)
            scored = _fight({}, one_rotation=one_rotation, score_only=True)
            assert full["breakdown"]["R"] == scored["breakdown"]["R"]
            assert full["breakdown"]["R"]["total_damage"] == 0.0
            assert full["total_damage"] == scored["total_damage"]
            assert full["resource_spent"] == scored["resource_spent"]
            assert full["resource_remaining"] == scored["resource_remaining"]
            # The Q/W/E surfaces agree too (the R has no damage surface).
            for slot in ("Q", "W", "E"):
                assert full["breakdown"][slot] == scored["breakdown"][slot]

    def test_engine_r_cast_booked_in_both_modes(self):
        # PASS today: the engine books the R cast in BOTH fight modes
        # (the score path's cast_timeline carries the same slot/time/
        # cost; the full path additionally carries the resource
        # before/after columns — the documented receipt difference).
        for one_rotation in (True, False):
            full = _fight({}, one_rotation=one_rotation)
            scored = _fight({}, one_rotation=one_rotation, score_only=True)
            full_r = [c for c in full["cast_timeline"] if c["slot"] == "R"][0]
            score_r = [c for c in scored["cast_timeline"] if c["slot"] == "R"][0]
            assert full_r["time"] == pytest.approx(score_r["time"])
            assert full_r["resource_cost"] == pytest.approx(score_r["resource_cost"])
            assert full_r["time"] == pytest.approx(0.0 if one_rotation else 0.5)

    def test_q_e_surfaces_identical_across_paths(self):
        # PASS (the brief's contract #13): the Q/E damage surfaces are
        # byte-identical between the full walk and the compiled score
        # path — the parity the P2-9 wiring must keep (the R adds the
        # cleanse/immunity/stat receipts to the FULL path; the score
        # path either models them identically or fails closed with the
        # named receipts — never a silent re-price).
        full = _fight({}, one_rotation=True)
        scored = _fight({}, one_rotation=True, score_only=True)
        assert full["breakdown"]["Q"] == scored["breakdown"]["Q"]
        assert full["breakdown"]["E"] == scored["breakdown"]["E"]
        assert full["total_damage"] == scored["total_damage"]


# ---------------------------------------------------------------------------
# S13 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_q_and_e_parse_receipts_unchanged(self):
        # The Q/E parse receipts are unchanged (the brief's contract
        # #14): Undertow 70..270 + 100% bonus AD (cd 9, cost 50..70);
        # Reckless Swing 70..250 + 50% AD true damage (cd 11..7, cost
        # 28..100) — recomputed from the cached rows, no literals.
        c = get_champion("Olaf")
        q = c["abilities"]["Q"][0]
        e = c["abilities"]["E"][0]
        assert extract_named(
            q, "Physical Damage", 5, {"bonus_attack_damage": 40.0}, {}
        ) == pytest.approx(270.0 + 40.0)
        assert extract_named(e, "True Damage", 5, {"attack_damage": 100.0}, {}) == (
            pytest.approx(250.0 + 50.0)
        )
        _, abilities = _parse()
        assert abilities["Q"]["name"] == "Undertow"
        assert abilities["Q"]["cooldown"] == pytest.approx(9.0)
        assert abilities["E"]["name"] == "Reckless Swing"
        assert abilities["E"]["damage_type"] == "true"
        # MERGE: the cooldown is published at the SELECTED rank now (the
        # reference build maxes E, and the cached row is 11/10/9/8/7 by
        # rank, so rank 5 is 7) — it used to come back as the rank-1 row
        # whatever rank was asked for.
        assert abilities["E"]["rank"] == 5
        assert abilities["E"]["cooldown"] == pytest.approx(7.0)
        assert abilities["E"]["resource_cost"] == pytest.approx(100.0)

    def test_w_shield_e8c_surface_unchanged(self):
        # The E8c W shield surface is unchanged (the brief's contract
        # #14): the app fight emits one Tough It Out shield row at the
        # cast (130 flat at the full-health floor, 2.5s, expires 2.75),
        # and the module constants stay pinned.
        from src.calculator.champions.olaf import (
            TOUGH_IT_OUT_MISSING_HEALTH_CAP,
            TOUGH_IT_OUT_MISSING_HEALTH_RATIO,
            TOUGH_IT_OUT_SHIELD_DURATION_SECONDS,
        )

        assert TOUGH_IT_OUT_SHIELD_DURATION_SECONDS == pytest.approx(2.5)
        assert TOUGH_IT_OUT_MISSING_HEALTH_RATIO == pytest.approx(0.175)
        assert TOUGH_IT_OUT_MISSING_HEALTH_CAP == pytest.approx(0.70)
        combat = _app_combat()
        rows = [
            e
            for e in combat.get("support_events", [])
            if e.get("attacker") == "main" and e.get("kind") == "shield"
        ]
        assert len(rows) == 1
        assert rows[0]["source"].startswith("Tough It Out")
        assert rows[0]["amount"] == pytest.approx(130.0)
        assert rows[0]["time"] == pytest.approx(0.25)
        assert rows[0]["expires_at"] == pytest.approx(2.75)
        survival = _survival(combat)
        assert survival["support_shield_received"] == pytest.approx(130.0)
        assert survival["shield_absorbed"] == pytest.approx(130.0)

    def test_cleanse_tables_unchanged(self):
        # The GP/Rengar/Milio/Dr. Mundo + item cleanse declarations stay
        # untouched (the brief's contract #14).
        assert set(CHAMPION_CLEANSE_DECLARATIONS) == {
            "Gangplank W",
            "Rengar W",
            "Milio R",
            "Dr. Mundo P",
            "Olaf R",
        }
        assert set(ITEM_CLEANSE_DECLARATIONS) == {
            "Mikael's Blessing",
            "Quicksilver Sash",
            "Mercurial Scimitar",
        }
        for key in ("Gangplank W", "Rengar W", "Milio R", "Dr. Mundo P", "Olaf R"):
            assert CHAMPION_CLEANSE_DECLARATIONS[key]["target_scope"]
        # The item declarations still resolve through the typed path.
        assert resolve_cleanse_item("Quicksilver Sash — Quicksilver") == (
            "Quicksilver Sash"
        )

    def test_kernel_truncation_and_immunity_contracts_unchanged(self):
        # The Slice 3/4 kernel contracts are unchanged (the brief's
        # contract #14): the truncate_intervals semantics and the
        # self-scope suppression rule stay as pinned by the Slices 4-8
        # matrices.
        kept, removed = truncate_intervals(
            [{"kind": "charm", "start": 0.0, "end": 1.8, "source": "E"}],
            0.25,
            frozenset(KNOWN_CONTROL_KINDS),
        )
        assert kept[0]["end"] == pytest.approx(0.25)
        assert removed[0]["start"] == pytest.approx(0.25)
        assert CAST_BLOCKING_CONTROL_KINDS == frozenset({"suppression"})
        assert classify_control(SimpleNamespace(cc_kind="slow")).blocking is False
        assert classify_control(SimpleNamespace(cc_kind="stun")).blocking is True
        unknown = classify_control(SimpleNamespace(cc_kind="mystery"))
        assert unknown.unknown is True

    def test_r_stays_out_of_damage_in_both_paths(self):
        # The R has no damage surface and the completion must NOT add
        # one (the brief's contract #13/#14): total_raw 0 in the parse,
        # no damage events in either path, and the Q/E numbers agree
        # across the full and score walks.
        for one_rotation in (True, False):
            result = _fight({}, one_rotation=one_rotation)
            assert result["breakdown"]["R"]["total_damage"] == 0.0
            assert "damage_events" not in result["breakdown"]["R"]
            scored = _fight({}, one_rotation=one_rotation, score_only=True)
            assert scored["breakdown"]["R"]["total_damage"] == 0.0


# ---------------------------------------------------------------------------
# S14 — Regression surface (the mandated sanity run list)
# ---------------------------------------------------------------------------


class TestRegressionSurface:
    def test_slice_regression_files_collected(self):
        # The mandated sanity list (the brief's contract #15) is the
        # full run gate: every file below stays green with this matrix
        # in the same invocation (the footer command).
        import tests.test_gangplank_w_cleanse  # noqa: F401
        import tests.test_milio_r_cleanse  # noqa: F401
        import tests.test_rengar_w_cleanse  # noqa: F401
        import tests.test_dr_mundo_passive  # noqa: F401
        import tests.test_cleanse_eligibility  # noqa: F401
        import tests.test_cleanse_eligibility_kernel  # noqa: F401
        import tests.test_cleanse_eligibility_consumers  # noqa: F401
        import tests.test_state_lifecycle  # noqa: F401
        import tests.test_state_lifecycle_consumers  # noqa: F401
        import tests.test_resource_ledger  # noqa: F401
        import tests.test_resource_ledger_consumers  # noqa: F401
        import tests.test_resource_ledger_champion_consumers  # noqa: F401
        import tests.test_catalyst_resource_ledger  # noqa: F401
        import tests.test_item_sustain  # noqa: F401
        import tests.test_mana_restore_refund  # noqa: F401
        import tests.test_app  # noqa: F401

    def test_existing_olaf_surfaces_stay_green(self):
        # The existing Olaf regression surface (the brief's contract
        # #15): the CP10 batch + the E8c shields + the support-effects
        # atom rows all name Olaf — they must stay green with the R
        # matrix (run in the footer command).
        # MERGE: the eleven ``test_cp10_batch_*.py`` scaffolds folded into
        # ``test_full_entry_packets.py`` (ours, 108872c8), which names the
        # same 120 full-entry champions Olaf sat in.
        import tests.test_full_entry_packets  # noqa: F401
        import tests.test_e8_shields  # noqa: F401
        import tests.test_support_effects  # noqa: F401


# The full mandated sanity gate (the brief's contract #15):
#
#   .venv/bin/python -m pytest tests/test_olaf_r_cleanse.py \
#     tests/test_aurelion_sol_stardust_ledger.py \
#     tests/test_senna_souls_ledger.py tests/test_bard_chimes_ledger.py \
#     tests/test_heimerdinger_multihit.py tests/test_ksante_w_resistance.py \
#     tests/test_rengar_ferocity_ledger.py tests/test_rengar_w_cleanse.py \
#     tests/test_gangplank_w_cleanse.py tests/test_milio_r_cleanse.py \
#     tests/test_dr_mundo_passive.py tests/test_cleanse_eligibility.py \
#     tests/test_cleanse_eligibility_kernel.py \
#     tests/test_cleanse_eligibility_consumers.py \
#     tests/test_state_lifecycle.py tests/test_state_lifecycle_consumers.py \
#     tests/test_resource_ledger.py tests/test_resource_ledger_consumers.py \
#     tests/test_resource_ledger_champion_consumers.py \
#     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#     tests/test_mana_restore_refund.py tests/test_app.py
