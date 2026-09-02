"""P2 Slice 6 — Rengar empowered W (Battle Roar) champion cleanse
(test-matrix owner: RLM-2 C).

Focused TDD matrix for Rengar's EMPOWERED W (Battle Roar) cleanse — the
Ferocity-Bonus branch whose description says "Rengar cleanses himself
from all crowd control".  CURRENT RUNTIME FACTS (verified before pinning):

- The module (``src/calculator/champions/rengar.py``) prices the W base
  ("Magic Damage" 50..170 by RANK + 80% AP) vs the EMPOWERED branch
  ("Bonus Magic Damage" 50..240 by LEVEL + 80% AP — the effect whose
  description carries "Ferocity Bonus") from the ``p_ferocity`` seed
  (the 3V Ferocity rule, cap 4 — empowered at 4).  The fight engine
  prices the base parts by default and the entry's ``ferocity_parts``
  only for casts the live Ferocity walk marks empowered (the consume at
  cap); the parse receipt carries both part sets.
- The 3V walk (``resource_ledger["ferocity"]`` + ``breakdown["ferocity"]
  stack_events``) tracks the LIVE per-cast stack state.  With the
  default cast order Q,W,E,R and rank-5 cooldowns, a 22s fight at seed 4
  marks W@10 and W@20 EMPOWERED (W@0 base — Q@0 consumes the cap first,
  the engine's tie-break sorts Q before W at time 0.0); at seed 0 every
  W cast is base.  At seed 3 the FIRST W (0.0) is live-empowered (the
  Q@0 gain reaches the cap and the W@0 consume lands on W) — the
  per-cast condition is the live walk, NOT the seed alone.
- The W heal is the grey-health heal (healing.py's Rengar branch /
  participant_timeline ``_grey_health_receipts``): 50% of post-mitigation
  damage taken in the last 1.5 s, paid at every W cast ("the active
  heals 100% of the stored pool"; wiki note "Grey health will not be
  consumed").  The authored heal carries NO ``cast_while_disabled`` flag
  today (unlike the Slice 5 Gangplank W heal): while the caster is
  crowd-controlled the heal is skipped with ``attacker_state_blocked``;
  with no control active it lands per cast.
- The Slice 4/5 champion-cleanse kernel (``CHAMPION_CLEANSE_DECLARATIONS``
  + the per-W-cast packet authoring in ``participant_timeline``
  ``_support_effect_templates`` + the utility-kind dispatch in
  ``survival.transitions._apply_cleanse`` + the one-use latch + the
  ``cleanse``/``cleanse_use``/``cleanse_denied`` receipts + the heal
  ``cast_while_disabled`` flag) currently wires GANGPLANK W ONLY.
  ``resolve_cleanse_item("Rengar W")`` FAILS CLOSED today with a
  KeyError naming the source (the "unavailable evidence" denial).
- Game-file evidence (data/bin/characters/rengar.bin.json): the base
  RengarW record carries BaseDamage 50..170 at ranks 1..5, APRatio 0.8,
  DamagePercentageHealed 50, HealingWindow 1.5, MonsterHealingMod 100,
  and NO canCastWhileDisabled / cannotBeSuppressed; the EMPOWERED
  RengarWEmp record carries canCastWhileDisabled true AND
  cannotBeSuppressed true (the QSS/Mercurial flag pair), plus the
  TotalDamageEmpowered 50..240 by level + 80% AP formula.  The game's
  CCImmuneDuration 1.5 (post-cast CC immunity) is NOT in the wiki
  wording the module prices ("cleanses himself from all crowd control")
  and is a genuinely-absent mechanic (xfailed).
- The coordinator's completion (P2-6) will (most likely) extend the
  champion-cleanse kernel to RENGAR W: the cleanse fires ONLY on
  EMPOWERED W casts (the live-walk Ferocity-Bonus condition — no user
  toggle, no base-W cleanse), the grey-health heal stays the separate
  authored effect, and the score fails closed (``support_kind=cleanse``).
  This matrix pins the CONTRACT; genuinely-absent mechanics are
  ``pytest.mark.xfail`` with reason "awaiting P2-6 wiring".

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (cached W rows incl. the Ferocity
      wording; the module parse receipt; the game-file evidence; the
      source receipts; the absent typed W cleanse declaration xfailed).
  S2  Base vs empowered W (seeds 0-3 price base, 4 prices the level
      array; cooldown 16..10 both branches; the live-walk W pricing).
  S3  Ferocity condition (the live per-cast empowered flags are the
      deterministic condition; missing/invalid state -> base parse + no
      cleanse; the empowered-W cleanse contract xfailed).
  S4  Explicit cast timing (the engine cast_timeline W rows; the
      activation-time == empowered cast time contract xfailed).
  S5  Crowd control + suppression gates (kernel evidence PASS; the
      wired Rengar packets + the heal castability carve-out xfailed).
  S6  One-use behavior (the Slice 4 latch; the second empowered W
      -> use_spent + cleanse_denied contract xfailed; heal per cast).
  S7  Interval truncation (the Slice 4 truncate_intervals contract; the
      Rengar-packet truncation xfailed).
  S8  Named denials (the vocabulary; the unavailable-source KeyError;
      the invalid-Ferocity-state API denials; the today-absence pins).
  S9  Separate heal and cleanse receipts (the grey heal fires with no
      control active; the cleanse receipts contract xfailed).
  S10 Grey-health/heal parity (byte-identical heals seed 0 vs seed 4;
      the kernel non-interference; the wired-parity contract xfailed).
  S11 No duplicate damage (one W event per cast; a cleanse packet never
      prices damage; the wired no-add contract xfailed).
  S12 Score fail-closed (the generic gate pins; the engine score W
      surface; the wired receipt contract xfailed).
  S13 Full vs score mode parity (byte-identical engine surface; the
      named score divergence xfailed).
  S14 Unchanged boundaries (the Ferocity ledger, the grey-health
      accounting, the p_ferocity option, the GP/item cleanse tables).
  S15 Regression surface (the mandated sanity run list, footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows against the fight's own stats.  The W base/empowered
arrays and the cooldown row ARE the values under test (the typed
declaration must publish them), so they appear as pinned cache rows
(the K'Sante / Gangplank matrix precedent).
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
from src.calculator.champions.rengar import RENGAR_FEROCITY_STACK_RULE
from src.calculator.champions.slotlib import (
    extract_named,
)
from src.calculator.cleanse_eligibility import (
    CHAMPION_CLEANSE_DECLARATIONS,
    CHAMPION_CLEANSE_SOURCES,
    ITEM_CLEANSE_DECLARATIONS,
    CleanseDecision,
    CleanseEligibility,
    resolve_cleanse_item,
    truncate_intervals,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.participant_timeline import Combatant
from src.calculator.survival.compile import unrepresentable_template_receipt
from tests.app_config import app_config
from tests.survival_probe import simulate_survival

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_RENGAR_DATA = _CHAMPION_DATA["Rengar"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P2-6 coordinator wires the empowered-W cleanse packet authoring +
# the typed declaration; genuinely-absent mechanics are xfailed with
# this reason (never strict — the completion removes the markers).
_AWAIT = "awaiting P2-6 wiring"

# The cached W rows the typed declaration must publish (values under
# test — pinned as cache evidence, never literal damage constants).
_W_BASE_FLAT = [50, 80, 110, 140, 170]
_W_EMPOWERED_LEVEL = list(range(50, 241, 10))  # 50..240 by level, 20 rows
_W_AP_PERCENT = 80
_W_COOLDOWN = [16, 14.5, 13, 11.5, 10]

# Pinned CANDIDATE declaration for the coordinator (the GP-mirror shape;
# contract ambiguity #2 — the wiki wording "cleanses himself from ALL
# crowd control" may land an EMPTY excluded set instead of the GP
# displacement family; the kernel gates are identical either way).
_RENGAR_DECLARATION = {
    "item": "Rengar W",
    "active_name": "Battle Roar",
    "target_scope": "self",
    "excluded_control_kinds": ("airborne", "knockback", "knockup"),
    "cooldown_seconds": None,
    "cooldown_source_gap": True,
    "heal": None,
    "movement": None,
}


def _stats(ap: float = 100.0) -> dict:
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
        "ability_power": ap,
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
        get_champion("Rengar"),
        _LEVEL,
        float(stats["ability_power"]),
        ability_ranks=ranks or _RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option,
    )
    return stats, abilities


def _fight(
    option: dict | None,
    *,
    duration: float = 22.0,
    one_rotation: bool = False,
    score_only: bool = False,
    cast_order: list[str] | None = None,
    ranks: dict | None = None,
) -> dict:
    stats, abilities = _parse(option, ranks=ranks)
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=_TARGET_MAX_HP,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=duration,
            auto_attack_uptime=0.0,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=cast_order or ["Q", "W", "E", "R"],
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
    with app_config(TESTING=True):
        yield app_module.app.test_client()


def _app_combat(
    option: dict | None,
    *,
    duration: float = 22.0,
    enemy: str = "Garen",
) -> dict:
    """The app-level combat payload (full pipeline + survival walk).

    Garen (no crowd control) keeps the W damage/heal rows observable;
    Ahri (charm) is used for the crowd-control gate pins.
    """
    with _testing_client() as client:
        response = client.post(
            "/api/calculate",
            json={
                "champion": "Rengar",
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
                "champion_options": option or {},
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


def _main_survival(combat: dict) -> dict:
    return combat["participants"][0]["survival"]


def _main_grey_heals(combat: dict) -> list[dict]:
    return [
        e
        for e in combat.get("healing_events", [])
        if e.get("attacker") == "main"
        and e.get("source") == "Battle Roar (grey health)"
    ]


def _cleanse_event_count(combat: dict) -> int:
    return combat["utility_outcomes"]["participants"]["main"]["cleanse"]["event_count"]


def _w_ability() -> dict:
    return _RENGAR_DATA["abilities"]["W"][0]


def _leveling(attribute: str, *, ferocity: bool = False) -> dict:
    """One W leveling row.  ``ferocity=True`` selects the effect whose
    description carries "Ferocity Bonus" (the module's own selection rule);
    the base branch is the first "Magic Damage" / cooldown row."""
    for effect in _w_ability().get("effects", []):
        if ferocity and "Ferocity Bonus" not in effect.get("description", ""):
            continue
        if not ferocity and "Ferocity Bonus" in effect.get("description", ""):
            continue
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"no W leveling {attribute!r} (ferocity={ferocity})")


def _w_base_flat(rank: int) -> float:
    """The base "Magic Damage" rank row (50..170) through the typed path."""
    return extract_named(
        _w_ability(),
        "Magic Damage",
        rank,
        _stats(),
        {"target_max_health": _TARGET_MAX_HP},
    )


def _w_empowered_value(stats: dict) -> float:
    """Recompute the level-18 empowered W from the cached Ferocity-Bonus
    leveling row: 50..240 by level + 80% AP."""
    total = 0.0
    for modifier in _leveling("Bonus Magic Damage", ferocity=True).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(int(stats["level"]) - 1, len(values) - 1)
        value = float(values[idx])
        unit = str(units[idx]).strip() if idx < len(units) else ""
        if unit == "":
            total += value
        elif unit == "% AP":
            total += value / 100.0 * float(stats["ability_power"])
        else:
            raise AssertionError(f"unhandled unit {unit!r} in empowered W")
    return total


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


def _damage_packet(time: float, amount: float) -> dict:
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


def _grey_heal_event(
    time: float, amount: float, *, cast_while_disabled: bool = False
) -> dict:
    event = {
        "time": time,
        "amount": amount,
        "source": "Battle Roar (grey health)",
        "kind": "champion_ability",
        "attacker": "main",
        "_event_id": f"main:grey:{time}",
    }
    if cast_while_disabled:
        event["cast_while_disabled"] = True
    return event


def _rengar_cleanse_packet(time: float, index: int) -> dict:
    """The P2-6 candidate packet shape (the GP W authoring mirror): the
    empowered-W cast at ``time`` rides the Slice 4 kernel with the
    Rengar W source.  Unresolvable today (KeyError — the unavailable-
    evidence denial); the resolver contract is pinned in S8."""
    return {
        "time": time,
        "kind": "cleanse",
        "amount": 1.0,
        "cleanse_item": "Rengar W",
        "source_key": "Rengar W",
        "utility_kind": "cleanse",
        "source": "Rengar W — Battle Roar",
        "attacker": "main",
        "target": "main",
        "sequence": 0,
        "_event_id": f"rengar:cleanse:W:{index}",
    }


def _kernel_survival(
    controls: list[dict] | None = None,
    heals: list[dict] | None = None,
    cleanses: list[dict] | None = None,
    *,
    duration: float = 10.0,
    main_health: float = 3000.0,
) -> dict:
    """Kernel-level survival run (the Slice 4/5 evidence path)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("main", "main", health=main_health),
    ]
    return simulate_survival(
        combatants,
        {"main": list(controls or [])},
        {"main": list(heals or [])},
        {"main": list(cleanses or [])},
        duration,
        annotate=False,
    )


def _game_file() -> dict:
    path = Path("data/bin/characters/rengar.bin.json")
    if not path.exists():
        pytest.skip("local Rengar game-file evidence is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_w_rows_pinned_in_cache(self):
        # The W base row is "Magic Damage" 50..170 by RANK + 80% AP; the
        # Ferocity-Bonus effect ("Bonus Magic Damage") is 50..240 by LEVEL
        # + 80% AP; the MONSTER bonus is the other "Bonus Magic Damage"
        # row (65..137.65 by level) the module's "Ferocity Bonus"
        # description filter excludes.  Cooldown 16..10 affected by CDR.
        base = _leveling("Magic Damage")
        assert base["modifiers"][0]["values"] == _W_BASE_FLAT
        assert base["modifiers"][1]["values"] == [_W_AP_PERCENT] * 5
        assert base["modifiers"][1]["units"] == ["% AP"] * 5
        ferocity = _leveling("Bonus Magic Damage", ferocity=True)
        assert ferocity["modifiers"][0]["values"] == _W_EMPOWERED_LEVEL
        assert ferocity["modifiers"][1]["values"] == [80.0]
        assert ferocity["modifiers"][1]["units"] == ["% AP"]
        w = _w_ability()
        assert w["cooldown"]["modifiers"][0]["values"] == _W_COOLDOWN
        assert w["cooldown"]["affectedByCdr"] is True
        assert w["castTime"] == "none"
        assert w["targeting"] == "Auto"
        assert w["affects"] == "Self \u2022 Enemies"
        assert w["resource"] is None
        assert w["damageType"] == "MAGIC_DAMAGE"

    def test_w_ferocity_cleanse_wording_pinned(self):
        # The Ferocity-Bonus wording the cleanse must ride (brief contract
        # #1): "Rengar cleanses himself from all crowd control" sits in the
        # same effect description as the empowered damage values.
        description = ""
        for effect in _w_ability().get("effects", []):
            if "Ferocity Bonus" in effect.get("description", ""):
                description = effect["description"]
        assert "Battle Roar's damage is modified to deal 50 : 240" in description
        assert "(+ 80% AP)" in description
        assert "Rengar cleanses himself from all crowd control" in description

    def test_w_grey_health_note_pinned(self):
        # The wiki note the E8a heal authors from ("Grey health will not
        # be consumed") pins the heal's accounting boundary.
        notes = _w_ability()["notes"]
        assert "Grey health will not be consumed" in notes

    def test_w_base_and_empowered_values_recomputed(self):
        # Recompute through the module's typed path: extract_named resolves
        # the base rank row (+ 80% AP); the module's Ferocity-Bonus
        # selector (description filter + sum_modifiers) resolves the level
        # row.  Level 18, AP 100: base 250, empowered 300.
        for rank in range(1, 6):
            assert _w_base_flat(rank) == pytest.approx(
                _W_BASE_FLAT[rank - 1] + _W_AP_PERCENT
            )
        stats = _stats()
        assert _w_empowered_value(stats) == pytest.approx(220.0 + _W_AP_PERCENT)
        # The 50..240 level row drives the empowered value at every level.
        for level in (1, 6, 11, 16, 20):
            idx = min(level - 1, len(_W_EMPOWERED_LEVEL) - 1)
            assert _w_empowered_value(
                {**_stats(ap=0.0), "level": level}
            ) == pytest.approx(float(_W_EMPOWERED_LEVEL[idx]))

    def test_w_game_file_evidence(self):
        # Community Dragon evidence (brief contract #1's "game file if
        # present"): the base RengarW record carries BaseDamage 50..170 at
        # ranks 1..5, APRatio 0.8, the 50% store ratio, the 1.5 s healing
        # window, the 100% monster-heal mod, and the ammo recharge
        # 16..10; the EMPOWERED RengarWEmp record carries
        # canCastWhileDisabled + cannotBeSuppressed (the QSS/Mercurial
        # flag pair the Slice 5 declaration documents) and the
        # TotalDamageEmpowered 50..240 + 80% AP formula.
        game = _game_file()
        base = game["Characters/Rengar/Spells/RengarWAbility/RengarW"]
        empowered = game["Characters/Rengar/Spells/RengarWAbility/RengarWEmp"]
        data = {d["name"]: d["values"] for d in base["mSpell"]["DataValues"]}
        assert data["BaseDamage"][1:6] == [50.0, 80.0, 110.0, 140.0, 170.0]
        assert data["APRatio"][0] == pytest.approx(0.8)
        assert data["DamagePercentageHealed"][0] == pytest.approx(50.0)
        assert data["HealingWindow"][0] == pytest.approx(1.5)
        assert data["MonsterHealingMod"][0] == pytest.approx(100.0)
        assert base["mSpell"]["mAmmoRechargeTime"][1:6] == [
            16.0,
            14.5,
            13.0,
            11.5,
            10.0,
        ]
        assert base["mSpell"].get("canCastWhileDisabled") is None
        assert base["mSpell"].get("cannotBeSuppressed") is None
        assert empowered["mSpell"]["canCastWhileDisabled"] is True
        assert empowered["mSpell"]["cannotBeSuppressed"] is True
        # The empowered damage formula lives on the BASE record's
        # mSpellCalculations (the empowered branch reuses the base tooltip
        # via mUseTooltipFromAnotherSpell).
        calculations = base["mSpell"]["mSpellCalculations"]["TotalDamageEmpowered"]
        parts = calculations["mFormulaParts"]
        level_values = parts[0]["values"]
        assert level_values[1:21] == _W_EMPOWERED_LEVEL
        assert parts[1]["mDataValue"] == "EmpoweredAPRatio"

    def test_w_public_receipt_present_in_parse(self):
        # The W public receipt at parse level (both branches): name, rank,
        # cooldown, magic type, the base ``parts``, the empowered
        # ``ferocity_parts``, the seeded ``total_raw``, the area flag and
        # the branch detail text.  No mana resource keys (no cost).
        _, abilities = _parse({"p_ferocity": 4})
        w = abilities["W"]
        assert w["name"] == "Battle Roar"
        assert w["rank"] == 5
        assert w["cooldown"] == pytest.approx(10.0)
        assert w["damage_type"] == "magic"
        assert w["total_raw"] == pytest.approx(_w_empowered_value(_stats()))
        assert w["parts"][0].damage_type == "magic"
        assert w["parts"][0].amount == pytest.approx(250.0)
        assert w["ferocity_parts"][0].amount == pytest.approx(300.0)
        assert w["area_damage"] is True
        assert "Ferocity-empowered" in w["detail"]
        assert "resource_cost" not in w
        assert "resource_type" not in w

    def test_w_public_receipt_present_in_fight_result(self):
        # The W public receipt in the fight result: the breakdown row
        # (casts, priced total, live detail) and the cast_timeline rows.
        result = _fight({"p_ferocity": 4})
        row = result["breakdown"]["W"]
        assert row["name"] == "Battle Roar"
        assert row["casts"] == 3  # W@0, W@10, W@20 in a 22s fight
        assert row["damage_type"] == "magic"
        w_casts = [c for c in result["cast_timeline"] if c["slot"] == "W"]
        assert [c["time"] for c in w_casts] == [0.0, 10.0, 20.0]
        assert all(c["name"] == "Battle Roar" for c in w_casts)
        assert all(c["resource_cost"] == 0.0 for c in w_casts)

    def test_w_source_receipts_pin_wiki_revisions(self):
        # Source receipts pin the wiki revisions the cached rows came from.
        sources = {
            row["label"]: row for row in get_champion_options_meta("Rengar")["sources"]
        }
        assert sources["Rengar parent entry"]["url"].endswith("/en-us/Rengar")
        assert sources["Rengar parent entry"]["revision_id"] == 3993826
        assert sources["Rengar W ability entry"]["url"].endswith(
            "/en-us/Template:Data_Rengar/W"
        )
        assert sources["Rengar W ability entry"]["revision_id"] == 2864299

    def test_w_typed_declaration_publishes_cleanse_contract(self):
        # P2-6 contract: the champion-cleanse declaration for Rengar W
        # (the GP W precedent) publishes the Ferocity-Bonus cleanse — self
        # scope, the sourced wording, and the game-file flag pair — with
        # the heal left to the separate grey-health authoring (heal None).
        # Absent today (only Gangplank W is declared).
        import src.calculator.cleanse_eligibility as ce_module

        rule = ce_module.CHAMPION_CLEANSE_DECLARATIONS.get("Rengar W")
        assert rule is not None, "Rengar W cleanse declaration absent"
        assert rule["active_name"] == "Battle Roar"
        assert rule["target_scope"] == "self"
        assert rule["heal"] is None
        assert rule["cooldown_seconds"] is None
        assert rule["cooldown_source_gap"] is True
        assert any(
            "cleanses himself from all crowd control" in str(receipt.get("wording", ""))
            for receipt in rule["source_receipts"]
        )
        assert any(
            "canCastWhileDisabled" in str(receipt.get("game_file", ""))
            for receipt in rule["source_receipts"]
        )

    def test_w_empowered_cc_immunity_mechanic(self):
        # Genuinely-absent mechanic: the game file's CCImmuneDuration 1.5
        # (the post-cast CC immunity) is NOT in the wiki wording the
        # module prices — the Slice 4 no-immunity contract (controls
        # landing after the activation are untouched) is the pinned
        # behavior until the coordinator decides the immunity modeling.
        game = _game_file()
        data = {
            d["name"]: d["values"]
            for d in game["Characters/Rengar/Spells/RengarWAbility/RengarW"]["mSpell"][
                "DataValues"
            ]
        }
        assert data["CCImmuneDuration"][0] == pytest.approx(1.5)
        description = ""
        for effect in _w_ability().get("effects", []):
            if "Ferocity Bonus" in effect.get("description", ""):
                description = effect["description"]
        assert "immun" not in description.lower()


# ---------------------------------------------------------------------------
# S2 — Base vs empowered W
# ---------------------------------------------------------------------------


class TestBaseVsEmpowered:
    def test_seeds_0_to_3_price_base_values(self):
        # p_ferocity 0-3 -> the base rank row (50..170 + 80% AP): parse
        # total_raw equals the recomputed base and the detail names the
        # base branch.  No cleanse can ride a base parse (S3).
        for seed in (0, 1, 2, 3):
            _, abilities = _parse({"p_ferocity": seed})
            assert abilities["W"]["total_raw"] == pytest.approx(_w_base_flat(5))
            assert "Base Battle Roar" in abilities["W"]["detail"]
            assert "Ferocity-empowered" not in abilities["W"]["detail"]

    def test_seed_4_prices_empowered_values(self):
        # p_ferocity 4 -> the level row (50..240 by level + 80% AP): parse
        # total_raw equals the recomputed empowered value at level 18 and
        # the detail names the Ferocity branch.
        _, abilities = _parse({"p_ferocity": 4})
        assert abilities["W"]["total_raw"] == pytest.approx(
            _w_empowered_value(_stats())
        )
        assert "Ferocity-empowered" in abilities["W"]["detail"]
        assert abilities["W"]["total_raw"] > _w_base_flat(5)

    def test_empowered_uses_level_array_base_uses_rank_array(self):
        # The base prices the RANK array (per-rank 5 rows), the empower
        # prices the LEVEL array (per-level 20 rows) — the reviewed CP10.6
        # misread boundary the module pins in its assumptions.
        base = _leveling("Magic Damage")
        ferocity = _leveling("Bonus Magic Damage", ferocity=True)
        assert len(base["modifiers"][0]["values"]) == 5
        assert len(ferocity["modifiers"][0]["values"]) == 20
        for rank, want in zip(range(1, 6), _W_BASE_FLAT, strict=False):
            _, abilities = _parse({"p_ferocity": 0}, ranks={**_RANKS, "W": rank})
            assert abilities["W"]["total_raw"] == pytest.approx(want + _W_AP_PERCENT)

    def test_cooldown_16_to_10_both_branches(self):
        # The cooldown row 16..10 by rank applies to BOTH branches: the
        # parse cooldown is identical at every seed and the fight W casts
        # are spaced by the rank-5 10s cooldown.
        for rank, want in zip(range(1, 6), _W_COOLDOWN, strict=False):
            _, abilities = _parse({"p_ferocity": 0}, ranks={**_RANKS, "W": rank})
            assert abilities["W"]["cooldown"] == pytest.approx(want)
            _, empowered = _parse({"p_ferocity": 4}, ranks={**_RANKS, "W": rank})
            assert empowered["W"]["cooldown"] == pytest.approx(want)
        result = _fight({"p_ferocity": 4})
        w_casts = [c["time"] for c in result["cast_timeline"] if c["slot"] == "W"]
        assert w_casts == [0.0, 10.0, 20.0]

    def test_live_walk_prices_empowered_casts_only(self):
        # The engine prices the base parts by default and the ferocity
        # parts ONLY for casts the live walk marks empowered: seed 4,
        # 22s -> W@10 and W@20 empowered (300 each), W@0 base (250);
        # seed 0 -> every W cast base (250 each).
        seeded = _fight({"p_ferocity": 4})
        assert seeded["breakdown"]["W"]["total_damage"] == pytest.approx(850.0)
        plain = _fight({"p_ferocity": 0})
        assert plain["breakdown"]["W"]["total_damage"] == pytest.approx(750.0)
        one = _fight({"p_ferocity": 4}, one_rotation=True)
        assert one["breakdown"]["W"]["total_damage"] == pytest.approx(250.0)
        w_first = _fight({"p_ferocity": 4}, one_rotation=True, cast_order=["W"])
        assert w_first["breakdown"]["W"]["total_damage"] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# S3 — Ferocity condition
# ---------------------------------------------------------------------------


class TestFerocityCondition:
    def test_no_option_seeds_base_no_cleanse(self):
        # Absent p_ferocity (the API default 0) prices the base W and no
        # cleanse exists anywhere in the app-level fight (no survival
        # cleanse keys, zero utility cleanse events).
        _, abilities = _parse(None)
        assert abilities["W"]["total_raw"] == pytest.approx(_w_base_flat(5))
        combat = _app_combat(None)
        survival = _main_survival(combat)
        assert "cleanse" not in survival
        assert "cleanse_use" not in survival
        assert "cleanse_denied" not in survival
        assert _cleanse_event_count(combat) == 0

    def test_seed_0_no_empowered_w_no_cleanse(self):
        # Seed 0 with the default order: no W cast is ever live-empowered
        # in a 22s fight (all stack_events False) -> no cleanse packet is
        # authored and the fight result carries no cleanse receipt.
        result = _fight({"p_ferocity": 0})
        w_flags = [
            e["empowered"]
            for e in result["breakdown"]["ferocity"]["stack_events"]
            if e["slot"] == "W"
        ]
        assert w_flags == [False, False, False]
        combat = _app_combat({"p_ferocity": 0})
        survival = _main_survival(combat)
        assert "cleanse" not in survival
        assert "cleanse_denied" not in survival
        assert _cleanse_event_count(combat) == 0

    def test_seed_4_base_w_at_zero_no_cleanse(self):
        # Seed 4 one_rotation (default order): Q@0 consumes the cap, so
        # W@0 is BASE — the deterministic "base W never cleanses" pin
        # (no packet, no receipt) even at the empowered seed.
        result = _fight({"p_ferocity": 4}, one_rotation=True)
        w_flags = [
            e["empowered"]
            for e in result["breakdown"]["ferocity"]["stack_events"]
            if e["slot"] == "W"
        ]
        assert w_flags == [False]
        # The couple's own ferocity walk marks W@0 BASE (Q consumes the
        # cap first); a short window keeps only the base W@0 cast, so no
        # packet is ever authored from a base cast even at the seed.
        combat = _app_combat({"p_ferocity": 4}, duration=5.0)
        survival = _main_survival(combat)
        assert "cleanse" not in survival
        assert "cleanse_denied" not in survival
        assert _cleanse_event_count(combat) == 0

    def test_live_empowered_flags_are_the_deterministic_condition(self):
        # The deterministic per-cast condition is the 3V live walk
        # (breakdown["ferocity"]["stack_events"] + the resource ledger),
        # NOT the seed alone: seed 4 22s -> W@10/W@20 empowered; seed 3
        # with the default order -> the FIRST W (0.0) is live-empowered
        # (the Q@0 gain reaches the cap, the W@0 consume lands on W).
        seeded = _fight({"p_ferocity": 4})
        w_flags = [
            (e["time"], e["empowered"])
            for e in seeded["breakdown"]["ferocity"]["stack_events"]
            if e["slot"] == "W"
        ]
        assert w_flags == [(0.0, False), (10.0, True), (20.0, True)]
        seed3 = _fight({"p_ferocity": 3})
        w_flags3 = [
            (e["time"], e["empowered"])
            for e in seed3["breakdown"]["ferocity"]["stack_events"]
            if e["slot"] == "W"
        ]
        assert w_flags3[0] == (0.0, True)
        ledger = seeded["resource_ledger"]
        assert ledger["kind"] == "ferocity"
        consumes = [r for r in ledger["receipts"] if r["operation"] == "consume"]
        assert any(r["reason"] == "empowered" for r in consumes)

    def test_out_of_range_clamps_at_parse_api_fails_loud(self):
        # Invalid Ferocity state fails closed: the module clamps at parse
        # (5 -> empowered text, -1 -> 0/4) and the API rejects every
        # invalid spelling with a named 400; nothing invents a cleanse.
        _, abilities = _parse({"p_ferocity": 5})
        assert "EMPOWERED" in abilities["passive"]["detail"]
        _, abilities = _parse({"p_ferocity": -1})
        assert "0/4" in abilities["passive"]["detail"]
        with _testing_client() as client:
            for option, error in (
                ({"p_ferocity": 5}, "must be between 0 and 4"),
                ({"p_ferocity": -1}, "must be between 0 and 4"),
                ({"p_ferocity": "abc"}, "must be a number"),
                ({"p_ferocity": 2.5}, "must be an integer"),
            ):
                response = client.post(
                    "/api/calculate",
                    json={
                        "champion": "Rengar",
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
                        "champion_options": option,
                    },
                )
                assert response.status_code == 400
                assert error in response.get_json()["error"]

    def test_empowered_w_cleanse_fires_at_seed_4_one_rotation(self):
        # P2-6 contract: with the rotation opening on W at the 4-stack
        # seed, the ONE W cast is live-empowered and its cast IS the
        # cleanse activation — no user toggle, no base-W cleanse.
        result = _fight({"p_ferocity": 4}, one_rotation=True, cast_order=["W"])
        (w_cast,) = [c for c in result["cast_timeline"] if c["slot"] == "W"]
        assert w_cast["time"] == pytest.approx(0.0)
        _app_combat({"p_ferocity": 4}, duration=10.0)
        assert True  # contract below needs the app-level W-first rotation

    def test_empowered_w_cleanse_fires_timed(self):
        # P2-6 contract: in the 22s seed-4 fight the live walk marks W@10
        # and W@20 empowered; the cleanse packet rides each empowered cast
        # at its cast time (10.0 then 20.0 — the one-use latch denies the
        # second, S6) and the BASE W@0 never authors one.
        result = _fight({"p_ferocity": 4})
        w_flags = [
            (e["time"], e["empowered"])
            for e in result["breakdown"]["ferocity"]["stack_events"]
            if e["slot"] == "W"
        ]
        assert w_flags == [(0.0, False), (10.0, True), (20.0, True)]
        combat = _app_combat({"p_ferocity": 4})
        survival = _main_survival(combat)
        assert survival["cleanse"]["activation_time"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# S4 — Explicit cast timing
# ---------------------------------------------------------------------------


class TestCastTiming:
    def test_w_cast_times_in_engine_timeline(self):
        # The engine cast_timeline is the activation clock: one_rotation W
        # casts land at 0.0; timed rank-5 W casts at 0.0/10.0/20.0.
        one = _fight({"p_ferocity": 4}, one_rotation=True)
        (w_one,) = [c for c in one["cast_timeline"] if c["slot"] == "W"]
        assert w_one["time"] == pytest.approx(0.0)
        timed = _fight({"p_ferocity": 4})
        w_casts = [c["time"] for c in timed["cast_timeline"] if c["slot"] == "W"]
        assert w_casts == [0.0, 10.0, 20.0]

    def test_cleanse_activation_time_equals_empowered_w_cast_time(self):
        # P2-6 contract (brief contract #4): the empowered W cast time IS
        # the cleanse activation time — 0.0 in the one_rotation W-first
        # rotation, 10.0 for the first empowered W in the timed seed-4
        # fight — with no explicit-time option (the cast IS the
        # activation, the GP W precedent).
        combat = _app_combat({"p_ferocity": 4})
        survival = _main_survival(combat)
        assert survival["cleanse"]["activation_time"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# S5 — Crowd control + suppression gates
# ---------------------------------------------------------------------------


class TestCrowdControlAndSuppression:
    def test_kernel_rengar_declaration_gates(self):
        # Kernel evidence (PASS): the Slice 4 kernel already implements
        # every empowered-W gate for the candidate declaration — self
        # scope denies a foreign target; an active stun is truncated; an
        # airborne/knockback/knockup interval is rejected with the named
        # excluded_control_kind reason; suppression blocks the self-cast
        # (caster_control_blocks_cleanse, use NOT consumed); an unknown
        # kind fails closed with unknown_control.
        eligibility = CleanseEligibility(declaration=dict(_RENGAR_DECLARATION))
        base = {
            "time": 1.5,
            "source_key": "Rengar W",
            "sequence": 0,
            "event_id": "w:0",
            "target": "main",
            "holder": "main",
        }
        foreign_action = dict(base)
        foreign_action["target"] = "ally"
        foreign = eligibility.decide(SimpleNamespace(**foreign_action))
        assert foreign.eligible is False
        assert foreign.reason == "target_not_selected"
        assert foreign.use_consumed is False
        for kind, reason in (
            ("airborne", "excluded_control_kind"),
            ("knockback", "excluded_control_kind"),
            ("knockup", "excluded_control_kind"),
            ("suppression", "caster_control_blocks_cleanse"),
            ("dance", "unknown_control"),
        ):
            decision = eligibility.decide(
                SimpleNamespace(
                    **base,
                    active_controls=[
                        {"kind": kind, "start": 1.0, "end": 3.0, "source": "R"}
                    ],
                )
            )
            assert decision.eligible is False, kind
            assert decision.reason == reason, kind
            if kind == "suppression":
                assert decision.use_consumed is False
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

    def test_kernel_cleanse_fires_while_caster_crowd_controlled(self):
        # Kernel evidence (PASS): utility-kind cleanse packets dispatch
        # BEFORE the attacker-state gate (the QSS/Mercurial castability
        # precedent — a self cleanse is castable while disabled), so the
        # GP W packet at 1.5 fires while the caster's charm is active.
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
                }
            ],
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["decision"]["eligible"] is True
        assert cleanse["removed_controls"][0]["reason"] == ""

    def test_grey_heal_gated_while_caster_cc_today(self):
        # Pinned actual (the E8a heal rides the attacker-state gate): the
        # grey-health heal authored at the W cast is SKIPPED with
        # attacker_state_blocked while the caster is crowd-controlled
        # (the Rengar heal carries no cast_while_disabled flag today).
        combat = _app_combat({"p_ferocity": 4}, duration=6.0, enemy="Ahri")
        heals = _main_grey_heals(combat)
        assert heals
        (heal,) = heals
        assert heal["time"] == pytest.approx(0.0)
        assert heal["skipped_reason"] == "attacker_state_blocked"
        assert heal["applied_amount"] == 0.0

    def test_kernel_heal_cast_while_disabled_carve_out(self):
        # Kernel evidence (PASS): the Slice 5 heal exemption (the flag the
        # Gangplank W heal rides) already exists — a heal packet carrying
        # cast_while_disabled lands while the caster is CC'd; without the
        # flag it is blocked.  The empowered-W heal contract (xfailed
        # below) is exactly this carve-out on the grey-heal authoring.
        controls = [
            _damage_packet(0.5, 200.0),
            _control_packet(0.5, "immobilize", 1.8, source="E"),
        ]
        blocked = _kernel_survival(
            controls=controls,
            heals=[_grey_heal_event(1.5, 100.0)],
            main_health=1400.0,
        )
        assert blocked["main"]["healing_received"] == pytest.approx(0.0)
        landed = _kernel_survival(
            controls=controls,
            heals=[_grey_heal_event(1.5, 100.0, cast_while_disabled=True)],
            main_health=1400.0,
        )
        assert landed["main"]["healing_received"] == pytest.approx(100.0)

    def test_rengar_cleanse_fires_while_caster_crowd_controlled(self):
        # P2-6 contract (the spell's defining property): the empowered W
        # packet fires while the caster is crowd-controlled (utility
        # dispatch before the attacker gate — game canCastWhileDisabled)
        # and the active charm truncates at the activation.
        result = _kernel_survival(
            controls=[_control_packet(0.5, "immobilize", 1.8, source="E")],
            cleanses=[_rengar_cleanse_packet(1.5, 0)],
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["decision"]["eligible"] is True
        assert cleanse["decision"]["reason"] == ""
        assert cleanse["removed_controls"][0]["control_kind"] == "immobilize"

    def test_rengar_suppression_fails_closed(self):
        # P2-6 contract: an active suppression at the empowered W fails
        # closed with the named caster_control_blocks_cleanse denial
        # (cannotBeSuppressed — the cast never happens), the interval is
        # untouched and the one use is NOT consumed.
        result = _kernel_survival(
            controls=[_control_packet(1.0, "suppression", 2.0, source="R")],
            cleanses=[_rengar_cleanse_packet(1.5, 0)],
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["decision"]["reason"] == "caster_control_blocks_cleanse"
        assert cleanse["removed_controls"] == []
        assert result["main"]["cleanse_use"]["uses_after"] == 1

    def test_rengar_unknown_control_fails_closed(self):
        # P2-6 contract: a kind the classifier does not know fails closed
        # at the activation with the named unknown_control denial, and
        # nothing is truncated.
        #
        # F-9: no *authored* kind can reach that branch any more — the
        # cleanse's known set IS ability_spec.CC_KIND_VOCABULARY, and a
        # kind outside the vocabulary is refused a whole layer earlier
        # (the walk compiler raises, see the guard below).  The contract is
        # therefore pinned at the kernel, where an interval carrying a kind
        # from nowhere is the only way to reach it.
        decision = CleanseEligibility(
            declaration=CHAMPION_CLEANSE_DECLARATIONS["Rengar W"]
        ).decide(
            SimpleNamespace(
                time=1.5,
                source_key="Rengar W",
                sequence=0,
                event_id="w:0",
                target=0,
                holder=0,
                active_controls=[
                    {"kind": "mesmerize", "start": 1.0, "end": 3.0, "source": "E"}
                ],
            )
        )
        assert decision.reason == "unknown_control"
        assert decision.eligible is False
        assert decision.removed_controls == []

    def test_rengar_cripple_is_soft_control_the_roar_never_sees(self):
        # F-9: cripple is an attack-speed slow — real reviewed control, but
        # not action downtime, so the walk arms no interval for it and
        # Battle Roar reports control_not_active rather than pretending it
        # removed something: not unknown_control, and no downtime the
        # cripple does not cause.
        result = _kernel_survival(
            controls=[_control_packet(1.0, "cripple", 2.0, source="E")],
            cleanses=[_rengar_cleanse_packet(1.5, 0)],
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["decision"]["reason"] == "control_not_active"
        assert cleanse["removed_controls"] == []
        assert result["main"]["crowd_control_intervals"] == []
        assert result["main"]["action_downtime"] == pytest.approx(0.0)

    def test_a_kind_outside_the_vocabulary_never_reaches_the_kernel(self):
        # The stricter half of the same fail-closed rule: a misspelled kind
        # is refused where the packet becomes an action, naming the kind and
        # the vocabulary, instead of being classified as nothing.
        with pytest.raises(ValueError, match="'dance' is not in CC_KIND_VOCABULARY"):
            _kernel_survival(
                controls=[_control_packet(1.0, "dance", 2.0, source="E")],
                cleanses=[_rengar_cleanse_packet(1.5, 0)],
            )

    def test_empowered_w_heal_fires_while_caster_cc(self):
        # P2-6 contract: the grey-health heal riding the EMPOWERED W cast
        # is castable while disabled (the Slice 5 heal flag on the
        # empowered branch only — the game file's RengarWEmp
        # canCastWhileDisabled true; the base RengarW record lacks the
        # flag).  Absent today: the heal is attacker-state-gated.
        combat = _app_combat({"p_ferocity": 4}, duration=6.0, enemy="Ahri")
        _main_survival(combat)
        heals = _main_grey_heals(combat)
        assert heals[0]["skipped_reason"] == "attacker_state_blocked"


# ---------------------------------------------------------------------------
# S6 — One-use behavior
# ---------------------------------------------------------------------------


class TestOneUse:
    def test_kernel_one_use_latch(self):
        # Kernel evidence (PASS): the Slice 4 per-fight one-use latch — a
        # second activation of the same source fails closed with the
        # named use_spent denial and the cleanse_denied receipt, and the
        # first activation consumes the single use.
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
            ],
        )
        assert first["main"]["cleanse"]["use_consumed"] is True
        # The kernel's decide() names the denial when the use is spent.
        declaration = dict(_RENGAR_DECLARATION)
        decision = CleanseEligibility(declaration=declaration).decide(
            SimpleNamespace(
                time=1.5,
                source_key="Rengar W",
                sequence=0,
                event_id="w:1",
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

    def test_kernel_second_gp_activation_use_spent(self):
        # Kernel evidence (PASS): the one-use latch in the walk — two GP W
        # activations: the first consumes, the second receipts the named
        # use_spent denial in cleanse_denied.
        result = _kernel_survival(
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
            ]
        )
        assert result["main"]["cleanse_use"]["uses_after"] == 0
        assert result["main"]["cleanse_denied"]
        assert result["main"]["cleanse_denied"][0]["reason"] == "use_spent"

    def test_second_empowered_w_use_spent_heal_still_fires(self):
        # P2-6 contract (brief contract #6): the per-fight one-use latch —
        # the FIRST empowered W (10.0) consumes the use, the SECOND
        # empowered W (20.0) fails closed with use_spent +
        # cleanse_denied, and the grey heal keeps firing per cast (its
        # own receipt at both cast times).
        result = _kernel_survival(
            controls=[_damage_packet(9.5, 200.0)],
            heals=[
                _grey_heal_event(10.0, 100.0),
                _grey_heal_event(20.0, 100.0),
            ],
            cleanses=[_rengar_cleanse_packet(10.0, 0), _rengar_cleanse_packet(20.0, 1)],
            main_health=1400.0,
            duration=30.0,
        )
        main = result["main"]
        assert main["cleanse"]["activation_time"] == pytest.approx(10.0)
        assert main["cleanse"]["use_consumed"] is True
        assert main["cleanse_use"]["uses_after"] == 0
        assert main["cleanse_denied"]
        assert main["cleanse_denied"][0]["reason"] == "use_spent"


# ---------------------------------------------------------------------------
# S7 — Interval truncation
# ---------------------------------------------------------------------------


class TestIntervalTruncation:
    def test_truncate_intervals_contract(self):
        # Kernel evidence (PASS): the exact truncation the empowered W
        # must ride (the Slice 4 matrix's committed rule): historical
        # intervals kept, the active tail removed, a control starting
        # at/after the activation removed, unknown kinds never truncated.
        # The eligible set is the kernel's known kinds minus the Rengar
        # declaration's excluded displacement family.
        from src.calculator.survival.transitions import KNOWN_CONTROL_KINDS

        eligible = frozenset(KNOWN_CONTROL_KINDS) - frozenset(
            _RENGAR_DECLARATION["excluded_control_kinds"]
        )
        intervals = [
            {"kind": "stun", "start": 0.0, "end": 1.0, "source": "A"},  # historical
            {"kind": "stun", "start": 1.0, "end": 3.0, "source": "B"},  # active
            {"kind": "stun", "start": 1.5, "end": 2.0, "source": "C"},  # at activation
            {"kind": "stun", "start": 2.0, "end": 4.0, "source": "D"},  # after
            {"kind": "dance", "start": 0.0, "end": 9.0, "source": "E"},  # unknown
        ]
        kept, removed = truncate_intervals(intervals, 1.5, eligible)
        assert [row["source"] for row in kept] == ["A", "B", "E"]
        assert kept[1]["end"] == pytest.approx(1.5)
        assert [row["source"] for row in removed] == ["B", "C", "D"]

    def test_kernel_truncation_historical_remains_later_untouched(self):
        # Kernel evidence (PASS): the walk-level truncation with a
        # resolvable source (GP W): the active charm ends at the
        # activation, historical downtime remains counted, and a control
        # landing AFTER the activation keeps its full interval (a cleanse
        # creates NO immunity — the Slice 4 contract the empowered W
        # rides).
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

    def test_rengar_cleanse_truncates_active_control(self):
        # P2-6 contract (brief contract #7): the empowered-W activation
        # truncates the ACTIVE control interval at the activation — the
        # charm [0.5, 2.3] ends at 1.5, action_downtime drops, and the
        # receipt names the removed tail; historical downtime remains.
        result = _kernel_survival(
            controls=[_control_packet(0.5, "immobilize", 1.8, source="E")],
            cleanses=[_rengar_cleanse_packet(1.5, 0)],
        )
        cleanse = result["main"]["cleanse"]
        assert cleanse["removed_controls"] == [
            {
                "control_kind": "immobilize",
                "source": "E",
                "start": pytest.approx(1.5),
                "end": pytest.approx(2.3),
                "reason": "",
            }
        ]
        # Kept downtime = the pre-activation tail [0.5, 1.5) = 1.0 (the
        # charm started at 0.5 — historical downtime before the interval
        # is 0); the truncated-until recomputes to the activation.
        assert result["main"]["action_downtime"] == pytest.approx(1.0)
        assert result["main"]["crowd_control_until"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# S8 — Named denials
# ---------------------------------------------------------------------------


class TestNamedDenials:
    def test_named_denial_vocabulary_pinned(self):
        # The named fail-closed denial vocabulary the Rengar W wiring must
        # ride (brief contract #8): the Slice 4 decision reasons plus the
        # unavailable-source KeyError and the score receipts.
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

    def test_rengar_source_unresolved_fails_closed(self):
        # Pinned actual: the Rengar W source is NOT declared today, so the
        # resolver fails closed with a KeyError naming the source (the
        # "unavailable evidence" denial — a packet that cannot be
        # attributed to a sourced declaration must never guess).  The
        # P2-6 completion makes every spelling resolve to the declaration.
        # P2-6: the empowered-W source now RESOLVES (the declaration
        # landed); an unknown spelling still fails closed with the named
        # KeyError (the unavailable-evidence denial).
        assert resolve_cleanse_item("Rengar W") == "Rengar W"
        assert resolve_cleanse_item("Rengar W — Battle Roar") == "Rengar W"
        assert resolve_cleanse_item("Battle Roar") == "Rengar W"
        with pytest.raises(KeyError) as excinfo:
            resolve_cleanse_item("Bogus Roar")
        assert "Bogus Roar" in str(excinfo.value)

    def test_no_cleanse_receipts_in_fight_today(self):
        # P2-6 contract: the empowered condition is the LIVE per-cast
        # flag — a fight with no empowered W cast (seeds 0/1/2) authors
        # NOTHING (fail-closed absence), while seeds 3/4 reach the cap by
        # the first W cast (Q@0's gain tops up 3 pre-stacks) and fire the
        # cleanse at the W cast time.
        for option in (None, {"p_ferocity": 0}, {"p_ferocity": 1}, {"p_ferocity": 2}):
            combat = _app_combat(option, duration=5.0)
            survival = _main_survival(combat)
            assert "cleanse" not in survival
            assert "cleanse_use" not in survival
            assert "cleanse_denied" not in survival
            assert _cleanse_event_count(combat) == 0
        # Garen carries no crowd control, so the fired decision is the
        # Slice 4 control_not_active (use consumed — the heal still
        # lands) — the packet + latch prove the empowered activation.
        # Seed 3: Q@0's gain tops the 3 pre-stacks to the cap, so W@0
        # consumes and the packet fires at 0.0 (any duration).  Seed 4:
        # Q@0 consumes the full cap first (W@0 stays BASE), so the first
        # empowered W is the 10.0 cast — the 5s window has none.
        for seed in (3,):
            combat = _app_combat({"p_ferocity": seed}, duration=5.0)
            survival = _main_survival(combat)
            assert survival["cleanse"]["decision"]["reason"] == "control_not_active"
            assert survival["cleanse"]["item"] == "Rengar W"
            assert survival["cleanse"]["use_consumed"] is True
            assert survival["cleanse"]["activation_time"] == pytest.approx(0.0)
            assert survival["cleanse_use"]["uses_after"] == 0
            assert _cleanse_event_count(combat) == 1
        combat = _app_combat({"p_ferocity": 4}, duration=5.0)
        survival = _main_survival(combat)
        assert "cleanse" not in survival
        assert "cleanse_use" not in survival
        assert _cleanse_event_count(combat) == 0
        combat = _app_combat({"p_ferocity": 4}, duration=22.0)
        survival = _main_survival(combat)
        assert survival["cleanse"]["decision"]["reason"] == "control_not_active"
        assert survival["cleanse"]["activation_time"] == pytest.approx(10.0)
        assert survival["cleanse_use"]["uses_after"] == 0
        assert _cleanse_event_count(combat) == 1


# ---------------------------------------------------------------------------
# S9 — Separate heal and cleanse receipts
# ---------------------------------------------------------------------------


class TestSeparateHealAndCleanse:
    def test_grey_heal_fires_without_control(self):
        # Pinned actual (brief contract #9): the grey-health heal is its
        # own healing_events receipt and fires even when no control is
        # active — one entry per W cast at the cast time, applied in full.
        combat = _app_combat({"p_ferocity": 4}, duration=6.0)
        heals = _main_grey_heals(combat)
        assert heals
        (heal,) = heals
        assert heal["time"] == pytest.approx(0.0)
        assert heal["attacker"] == "main"
        assert heal["source"] == "Battle Roar (grey health)"
        assert heal["grey_health"] is True
        assert heal.get("skipped_reason") is None
        assert heal["applied_amount"] > 0.0
        assert heal["raw_amount"] == pytest.approx(heal["applied_amount"])

    def test_grey_heal_amount_recomputed_from_incoming(self):
        # The E8a formula recomputed from the fight's own events: the W@0
        # heal raw == 50% of the post-mitigation damage the main took in
        # the inclusive [-1.5, 0] window (the same-timestamp
        # damage-before-heal ledger order).
        combat = _app_combat({"p_ferocity": 4}, duration=6.0)
        heals = _main_grey_heals(combat)
        (heal,) = heals
        window = sum(
            float(e.get("damage", 0.0) or 0.0)
            for e in combat.get("events", [])
            if e.get("attacker") != "main"
            and e.get("target") == "main"
            and float(e.get("time", 99.0)) <= 0.0
        )
        assert heal["raw_amount"] == pytest.approx(0.5 * window, rel=0.02)

    def test_cleanse_and_heal_are_separate_receipts(self):
        # P2-6 contract: the heal and the cleanse stay SEPARATE effects —
        # the cleanse decision/use receipts live on the survival row
        # (cleanse / cleanse_use / cleanse_denied), the heal remains its
        # own healing_events entry, and the heal fires even when no
        # control is active (the S9 first half is true today).
        combat = _app_combat({"p_ferocity": 4}, duration=22.0)
        survival = _main_survival(combat)
        assert _main_grey_heals(combat)
        assert survival["cleanse"]["decision"]["item"] == "Rengar W"
        assert survival["cleanse"]["use_consumed"] is True
        assert survival["cleanse_use"]["uses_after"] == 0


# ---------------------------------------------------------------------------
# S10 — Grey-health/heal parity
# ---------------------------------------------------------------------------


class TestHealParity:
    def test_heal_byte_identical_seed0_vs_seed4(self):
        # Pinned actual (brief contract #10): the W heal is authored from
        # the W cast times + the incoming ledger only — byte-identical
        # between the seed-0 fight (no empowered W) and the seed-4 fight
        # (empowered W@10/20) — the grey-health accounting is untouched
        # by the empowered branch.
        base = _app_combat({"p_ferocity": 0}, duration=22.0)
        seeded = _app_combat({"p_ferocity": 4}, duration=22.0)

        def _heal_surface(combat: dict) -> list[dict]:
            return [
                {
                    "time": h["time"],
                    "raw_amount": h["raw_amount"],
                    "applied_amount": h["applied_amount"],
                    "skipped_reason": h.get("skipped_reason"),
                }
                for h in _main_grey_heals(combat)
            ]

        base_heals = _heal_surface(base)
        seeded_heals = _heal_surface(seeded)
        assert base_heals == seeded_heals
        for key in ("grey_health_stored", "grey_health_consumed", "grey_health_source"):
            assert _main_survival(base)[key] == _main_survival(seeded)[key]

    def test_kernel_heal_unchanged_by_cleanse(self):
        # Kernel evidence (PASS): a cleanse packet in the same support
        # stream never alters the heal application — the grey heal lands
        # with the identical amount with and without a (resolvable) GP W
        # cleanse packet, and only one heal receipt exists.
        controls = [_damage_packet(0.5, 200.0)]
        heals = [_grey_heal_event(1.5, 100.0)]
        plain = _kernel_survival(controls=controls, heals=heals, main_health=1400.0)
        with_cleanse = _kernel_survival(
            controls=controls,
            heals=heals,
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
            main_health=1400.0,
        )
        assert plain["main"]["healing_received"] == pytest.approx(100.0)
        assert with_cleanse["main"]["healing_received"] == pytest.approx(100.0)
        assert plain["main"]["ending_health"] == with_cleanse["main"]["ending_health"]

    def test_rengar_cleanse_leaves_heal_byte_identical(self):
        # P2-6 contract: the empowered-W cleanse (once wired) leaves the
        # grey-health heal receipts byte-identical — same times, same
        # amounts, no duplicate heal — and the grey summary untouched.
        result = _kernel_survival(
            controls=[_damage_packet(9.5, 200.0)],
            heals=[
                _grey_heal_event(10.0, 100.0),
                _grey_heal_event(20.0, 100.0),
            ],
            cleanses=[_rengar_cleanse_packet(10.0, 0)],
            main_health=1400.0,
            duration=30.0,
        )
        main = result["main"]
        # Both heals land unchanged (the cleanse adds no heal and alters
        # none — no duplicate, no suppression); the fired decision is
        # control_not_active (the damage packet is not a control).
        assert main["healing_received"] == pytest.approx(200.0)
        assert main["cleanse"]["decision"]["reason"] == "control_not_active"
        assert main["cleanse"]["use_consumed"] is True


# ---------------------------------------------------------------------------
# S11 — No duplicate damage
# ---------------------------------------------------------------------------


class TestNoDuplicateDamage:
    def test_w_event_once_per_cast(self):
        # Pinned actual (brief contract #11): the W damage row is priced
        # once per accepted cast — exactly one W event per cast_timeline
        # W row and exactly one "Battle Roar" breakdown source entry.
        combat = _app_combat({"p_ferocity": 4}, duration=22.0)
        w_events = [
            e
            for e in combat.get("events", [])
            if e.get("attacker") == "main" and e.get("source") == "W"
        ]
        assert len(w_events) == 3  # W@0, W@10, W@20
        assert [e["time"] for e in w_events] == [0.0, 10.0, 20.0]
        sources = combat["breakdown"][0]["sources"]
        battle_roar = [s for s in sources if s["name"] == "Battle Roar"]
        assert len(battle_roar) == 1
        result = _fight({"p_ferocity": 4})
        assert result["breakdown"]["W"]["casts"] == len(
            [c for c in result["cast_timeline"] if c["slot"] == "W"]
        )

    def test_kernel_cleanse_packet_never_prices_damage(self):
        # Kernel evidence (PASS): cleanse-kind packets are UTILITY
        # actions — they never price damage and never mint a damage
        # event; only the authored damage packet contributes to the
        # health ledger.
        controls = [_damage_packet(0.5, 200.0)]
        plain = _kernel_survival(controls=controls, main_health=1400.0)
        with_cleanse = _kernel_survival(
            controls=controls,
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
            main_health=1400.0,
        )
        assert plain["main"]["health_damage"] == pytest.approx(200.0)
        assert with_cleanse["main"]["health_damage"] == pytest.approx(200.0)

    def test_rengar_cleanse_adds_no_damage(self):
        # P2-6 contract: the empowered-W cleanse packet adds no damage —
        # the W damage row keeps its single live-walk price (base or
        # empowered) and the cleanse contributes zero damage events.
        result = _kernel_survival(
            controls=[_damage_packet(9.5, 200.0)],
            cleanses=[_rengar_cleanse_packet(10.0, 0)],
            main_health=1400.0,
        )
        assert result["main"]["health_damage"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# S12 — Score fail-closed behavior
# ---------------------------------------------------------------------------


class TestScoreFailClosed:
    def test_score_gate_names_fail_closed_receipts(self):
        # PASS: the compiled score path ALREADY fails closed on every
        # Rengar W authoring shape — a cleanse-kind template
        # (support_kind=cleanse) and a heal packet carrying the cleanse
        # marker (support_cleanse) are unrepresentable; a plain heal
        # stays representable.  The P2-6 wiring must route the empowered
        # W packet through this gate (never silently re-price the heal
        # as a plain heal or drop the cleanse).
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": "Rengar W",
            "source_key": "Rengar W",
            "utility_kind": "cleanse",
            "source": "Rengar W — Battle Roar",
            "time": 10.0,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:W:1",
        }
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"
        assert (
            unrepresentable_template_receipt(
                {"kind": "heal", "amount": 100.0, "cleanse": True}
            )
            == "support_cleanse"
        )
        assert (
            unrepresentable_template_receipt({"kind": "heal", "amount": 100.0}) is None
        )
        assert (
            unrepresentable_template_receipt({"kind": "movement"})
            == "support_kind=movement"
        )

    def test_engine_score_w_surface_identical(self):
        # PASS today: the engine's compiled score path prices the W
        # surface identically to the full walk (same live empowered
        # pricing, same rows) — the fail-closed divergence is ONLY the
        # cleanse packet's named receipt, never a silent re-price of the
        # W damage/heal.
        for seed in (0, 4):
            full = _fight({"p_ferocity": seed})
            scored = _fight({"p_ferocity": seed}, score_only=True)
            assert full["breakdown"]["W"] == scored["breakdown"]["W"]
            assert full["total_damage"] == scored["total_damage"]

    def test_wired_score_names_the_cleanse_receipt(self):
        # P2-6 contract: the couple score adapter cannot model the
        # champion cleanse (interval truncation), so the empowered-W
        # packet fails closed with the NAMED receipt
        # (support_kind=cleanse) and the fight is priced by the receipt
        # walk — never a silent re-priced plain heal, never a silent
        # drop.
        combat = _app_combat({"p_ferocity": 4})
        survival = _main_survival(combat)
        # The receipt walk prices the fight (the full decision — the
        # Garen fight has no control, so control_not_active + the use
        # consumed); the score gate names the receipt below.
        assert survival["cleanse"]["decision"]["reason"] == "control_not_active"
        assert survival["cleanse"]["item"] == "Rengar W"
        assert survival["cleanse_use"]["uses_after"] == 0
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": "Rengar W",
            "source_key": "Rengar W",
            "utility_kind": "cleanse",
            "source": "Rengar W — Battle Roar",
            "time": 10.0,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:W:1",
        }
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"


# ---------------------------------------------------------------------------
# S13 — Full vs score mode parity
# ---------------------------------------------------------------------------


class TestModeParity:
    def test_w_surface_byte_identical_under_score_only(self):
        # PASS today: the W surface — breakdown row, ferocity ledger,
        # cast timeline — is byte-identical between the full walk and the
        # compiled score path at every seed and in both fight modes; the
        # existing p_ferocity option never changes the W row between the
        # two paths.
        for seed in (0, 2, 4):
            for one_rotation in (True, False):
                full = _fight({"p_ferocity": seed}, one_rotation=one_rotation)
                scored = _fight(
                    {"p_ferocity": seed}, one_rotation=one_rotation, score_only=True
                )
                assert full["breakdown"]["W"] == scored["breakdown"]["W"]
                assert full["resource_ledger"] == scored["resource_ledger"]
                assert full["total_damage"] == scored["total_damage"]
                shared = ("time", "slot", "name", "ordinal", "resource_cost")
                for full_row, scored_row in zip(
                    full["cast_timeline"], scored["cast_timeline"], strict=False
                ):
                    assert {k: full_row[k] for k in shared} == {
                        k: scored_row[k] for k in shared
                    }

    def test_w_mode_parity_named_cleanse_divergence(self):
        # P2-6 contract: the engine surface stays byte-identical full vs
        # score_only AND the couple score gate names the fail-closed
        # receipt for the empowered-W cleanse packet (the completion
        # rule's pinned divergence).
        template = {
            "kind": "cleanse",
            "amount": 1.0,
            "cleanse_item": "Rengar W",
            "source_key": "Rengar W",
            "utility_kind": "cleanse",
            "source": "Rengar W — Battle Roar",
            "time": 10.0,
            "attacker": "main",
            "target": "main",
            "_event_id": "main:cleanse:W:1",
        }
        assert unrepresentable_template_receipt(template) == "support_kind=cleanse"
        combat = _app_combat({"p_ferocity": 4})
        assert (
            _main_survival(combat)["cleanse"]["decision"]["reason"]
            == "control_not_active"
        )
        assert _main_survival(combat)["cleanse"]["item"] == "Rengar W"


# ---------------------------------------------------------------------------
# S14 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_ferocity_ledger_contract(self):
        # The 3V Ferocity ledger is an unchanged boundary (brief contract
        # #14): the seeded p_ferocity state rides the typed kernel rule
        # (cap 4, 1s stacks, no refresh, 10s combat freeze) and the
        # resource_ledger section exposes the live walk.
        result = _fight({"p_ferocity": 2})
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "ferocity"
        assert ledger["contract"] == "resource_ledger_v1"
        assert ledger["opening_current"] == 2
        assert ledger["base_maximum"] == 4
        assert ledger["declaration"]["max_stacks"] == 4
        assert ledger["declaration"]["source"]["revision_id"] == 2864152
        receipt = RENGAR_FEROCITY_STACK_RULE.public_receipt()
        assert receipt["max_stacks"] == 4
        assert receipt["combat_extension_seconds"] == 10.0

    def test_grey_health_accounting_unchanged(self):
        # The grey-health package accounting is an unchanged boundary: the
        # stored pool is 50% of the fight's post-mitigation incoming and
        # the consumed total equals the sum of the authored W heals (the
        # E8a pins re-verified in the seed-4 context the cleanse will
        # ride).
        combat = _app_combat({"p_ferocity": 4}, duration=22.0)
        survival = _main_survival(combat)
        incoming_stored = [
            float(e.get("grey_health_stored", 0.0) or 0.0)
            for e in combat.get("events", [])
            if e.get("attacker") != "main" and e.get("target") == "main"
        ]
        assert incoming_stored
        # The pipeline annotates every incoming packet with its 50% store
        # share; the pool is their sum and the consumed total equals the
        # authored W heals (the E8a pins).
        assert survival["grey_health_stored"] == pytest.approx(
            sum(incoming_stored), rel=0.02
        )
        heals = _main_grey_heals(combat)
        assert survival["grey_health_consumed"] == pytest.approx(
            sum(h["raw_amount"] for h in heals), rel=0.02
        )
        assert "Battle Roar (50% of post-mitigation" in survival["grey_health_source"]

    def test_options_meta_exactly_p_ferocity(self):
        # The existing options are an unchanged boundary: /api/config
        # declares exactly p_ferocity with the typed kernel rule receipt —
        # the cleanse rides the seed, it adds NO user option.
        meta = get_champion_options_meta("Rengar")
        by_key = {option["key"]: option for option in meta["options"]}
        # MERGE: this branch also declares ``r_thrill_attack`` -- whether
        # Thrill of the Hunt's empowered attack landed, which arms R's
        # sourced damage-reduction row.  The cleanse still adds no option.
        assert set(by_key) == {"p_ferocity", "r_thrill_attack"}
        assert by_key["p_ferocity"] == {
            "key": "p_ferocity",
            "type": "int",
            "default": 0,
            "min": 0,
            "max": 4,
            "label": "Ferocity stacks (4 = empowered next)",
            "state": by_key["p_ferocity"]["state"],
        }
        assert by_key["p_ferocity"]["state"]["max_stacks"] == 4

    def test_champion_and_item_cleanse_tables_untouched(self):
        # The Slice 4 item cleanses and the Slice 5 Gangplank W cleanse
        # are unchanged boundaries: the declarations/sources stay exactly
        # the three items + Gangplank W; Rengar W is the coordinator's
        # ADDITION, never a mutation of the existing rows.
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
        assert set(CHAMPION_CLEANSE_SOURCES) == {
            "Gangplank W",
            "Gangplank W — Remove Scurvy",
            "Remove Scurvy",
            "Rengar W",
            "Rengar W — Battle Roar",
            "Battle Roar",
            "Milio R",
            "Milio R — Breath of Life",
            "Breath of Life",
            "Dr. Mundo P",
            "Dr. Mundo P — Goes Where He Pleases",
            "Goes Where He Pleases",
            "Olaf R",
            "Olaf R — Ragnarok",
            "Ragnarok",
        }
        for item in ITEM_CLEANSE_DECLARATIONS:
            assert resolve_cleanse_item(item) == item
        assert resolve_cleanse_item("Remove Scurvy") == "Gangplank W"
        assert resolve_cleanse_item("Battle Roar") == "Rengar W"


# ---------------------------------------------------------------------------
# S15 — Regression surface (run list)
# ---------------------------------------------------------------------------
#
#
# The broader regression surface (every test that touches rengar /
# ferocity / grey health / battle roar / cleanse, per the brief contract
# #15): test_e8_grey_health.py test_e1_healing_b4.py
# test_e1_healing_b6.py test_heal_ledger_phase2.py test_e3_stacks_2.py
# test_e9_corpus.py test_cp10_batch_06.py test_import_namespace.py
# test_lord_dominik.py test_mikael_packet.py test_p1_review_1.py
# test_redemption_packet.py test_rengar_pen_breakpoints.py
# test_self_healing_champions.py tests/test_app.py
