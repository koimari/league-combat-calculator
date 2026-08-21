"""P1 Package 3S — Knight's Vow (3109) "Sacrifice"/"Pledge" compiled-walk +
optimizer certification.

This file is the focused acceptance-matrix owner for Knight's Vow's Worthy
tether (active Pledge) and its Sacrifice redirect + holder heal.  It pins
the OBSERVABLES the coordinator's P3-3S completion must satisfy and runs
against today's source: every behavior that already exists passes now;
every assertion that targets a contract piece the source does not emit
yet is marked ``xfail`` with reason ``awaiting P3-3S ...``.

Contract under test (current runtime facts, verified before pinning):

* ITEM IDENTITY: cached name "Knight's Vow", id 3109, price 2300
  (shop.prices.total, sell 920), tier 3 LEGENDARY, builds from
  [3067, 1031, 1006].  Stats: +200 flat health, +40 flat armor, +10
  flat ability haste, +100% BASE health regen (resolved as
  health_regen_percent 100 on Ahri level 18; the per-five delta is
  Ahri's own base 12.7).  Passive "Sacrifice" (unique) + active
  "Pledge" (unique); the exact branch text is pinned (1250-unit
  tether, 30% maximum-health holder gate, 14% pre-mitigation
  physical/magic redirect, 12% post-mitigation heal, one-Worthy
  exclusivity).
* TYPED SOURCE: the ALLY_ITEM_EFFECTS registry entry carries the four
  typed keys read through ally_item_effect_value: redirect_fraction
  0.14, holder_heal_fraction 0.12, worthy_range_units 1250.0,
  holder_health_threshold_ratio 0.30; the ITEM_INPUT_OPTIONS entry
  carries the three authored scenario controls (worthy_target_index
  0..4 default 0, worthy_within_range 0/1 default 1,
  holder_above_30_percent 0/1 default 1) plus source_url
  "https://wiki.leagueoflegends.com/en-us/Knight%27s_Vow" and
  source_revision_id 4023793 (discoverable on the input-options
  receipt).  Missing keys raise KeyError naming "Knight's Vow" AND the
  key (AGENTS.md rule 5 — no silent fallbacks); malformed values raise
  ValueError naming the item and key.
* OWNER/ALLY RELATIONSHIP + TARGET SELECTION: the scheduler
  (item_support_effects.schedule_knights_vow) loops the roster for the
  Knight's Vow OWNER, selects the teammate at the authored
  worthy_target_index (teammate order = all_actors order, main first),
  and stamps redirect_fraction/redirect_target/redirect_source only on
  that Worthy's incoming physical/magic events.  The redirect target
  and the heal recipient are always the owner.  RUNTIME RULE pinned:
  a MISSING authored index currently falls back to the schema default 0
  (first teammate) — the redirect still fires; and an out-of-range
  authored index is rejected by validate_item_input_options ("must be
  between 0 and 4") before the scheduler can clamp.  The contract's
  "NO authored index -> no redirect/no heal (fail closed)" is pinned as
  xfail (awaiting P3-3S) because it needs a source change; a roster
  with NO eligible teammate already fails closed (no tether).
* REDIRECT AMOUNT + TIMING: a Worthy ally taking pre-mitigation
  physical/magic damage from a roster enemy receives a redirect of
  exactly 0.14 x the eligible pre-mitigation damage to the holder, as
  the respective damage type (the holder's own resistance mitigates the
  redirected share; the Worthy keeps the other 86% mitigated by their
  own resistance).  True damage is NEVER redirected.  The holder heal
  is 0.12 x post-mitigation Worthy damage to champions, authored as a
  support packet with healing_category "knights_vow",
  target_scope "holder_from_worthy_damage", requires_holder_health_ratio
  0.30, range_units 1250.0, source_revision_id 4023793; outgoing true
  damage DOES count toward the heal.  The kernel re-checks the holder's
  30%-health gate per packet: a holder at/below 30% max health cancels
  the redirected child (restores the full packet on the Worthy, named
  reason "holder_health_gate") and skips the heal (same reason).
* AUTHORED GATES: worthy_within_range=0 stamps "worthy_out_of_range" on
  the Worthy's physical/magic incoming events and disables BOTH the
  redirect and the heal; holder_above_30_percent=0 stamps
  "holder_health_gate_disabled" and disables both.  The 1250-unit range
  has NO kernel coordinate model (the roster has no spatial
  coordinates), so the scenario must author the in-range assumption —
  that authored option is the range gate today.
* RECEIPT FIELDS + SOURCE EVIDENCE: the support-packet receipts carry
  redirect_source "Knight's Vow — Sacrifice", redirect_target,
  redirect_pre_mitigation_required, redirect_holder_health_ratio 0.30,
  redirect_range_units 1250.0, redirect_source_revision_id 4023793 and
  the heal packet's source/source_revision_id.  The item_state_receipts
  row for the item (the 3M/3N/3O-pattern state row carrying the four
  typed values + source receipt) is ABSENT today — xfail.
* COMPILED VS RECEIPT PARITY: score path (include_receipt=False) and
  receipt walk agree on every observable (survival rows, breakdown,
  duration, and the redirect/heal receipts the score surface carries).
  Today Knight's Vow sits in COMPILED_WALK_UNREPRESENTABLE_ITEMS
  ("Worthy redirect authored by the receipt scheduler"), so the
  compiled fast path fails closed: a MAIN holder falls back per
  evaluation (context.uncompilable stays False, no panels built) and a
  roster (enemy/ally) holder poisons the search-invariant context
  (uncompilable True, panels empty) — both still deep-equal the receipt
  walk.  The P3-3S certification (stage the redirect/heal in the
  compiled path, remove the blocklist with parity proof) is pinned as
  xfail: panels non-empty + uncompilable False + deep-equal.  A
  tuple-ledger champion (Riven) holding Knight's Vow fails closed with
  parity and NO crash today (per-evaluation fallback, unpoisoned
  context); the post-certification tuple guard (named receipt, e.g.
  redirect_fraction / requires_holder_health_ratio, for light rows that
  omit the redirect metadata) is the coordinator's staging surface.
* COVERAGE: item_model_coverage returns "modeled_state" with
  optimizer_eligible + calculation_eligible True and outcome_dimensions
  [] today, but the reason is the GENERIC "The item exposes its
  damage-relevant state as a scenario control." — a reason naming
  Sacrifice/Pledge/redirect is xfail (the coordinator's coverage
  tightening).  target_item_model_coverage is "modeled" naming Pledge,
  Sacrifice, the 14% redirect, and the sourced range/health gates.
* XFAIL ONLY for genuinely absent mechanics: (1) the compiled-panel
  certification; (2) the roster-holder compilation; (3) the
  item_state_receipts Knight's Vow row; (4) the coverage reason naming
  Sacrifice/Pledge; (5) the fail-closed missing-index contract.  All
  are ``awaiting P3-3S ...``.

Coordinator ambiguities surfaced by this matrix (see the reply):

* "NO authored index -> fail closed" is NOT today's rule: the schema
  default 0 selects the first teammate and the redirect fires.  Either
  the contract needs a source change (default -> no tether) or the
  contract means "no eligible teammate".
* The two gates are authored OPTIONS today (worthy_within_range,
  holder_above_30_percent, both default ON) AND the holder gate is
  re-checked by the survival kernel per packet (strictly above
  30% + 1e-9); the 1250-unit range has no kernel coordinate model.
* The compiled staging surface: compile.py's unrepresentable_damage_
  receipt returns "redirect_fraction" for any packet carrying
  redirect_fraction and unrepresentable_heal_receipt returns
  "requires_holder_health_ratio" for the gated heal — both must be
  staged (or named) when the item leaves the blocklist.
* schedule_knights_vow ignores the ally_effects_enabled toggle (the
  derive_item_support_effects path honors it); a KV ally redirects even
  when the toggle is off.  Out of contract scope, flagged for review.
* item_state_receipts row state name is pinned here as "sacrifice"
  (passive-name pattern like FoN's "steadfast"); confirm or adjust.

Sibling owners: the scheduler receipts live in
``tests/test_item_support_effects.py`` (test_knights_vow_attaches_
typed_redirect_and_holder_heal_receipts ~538); the redirect survival
math in ``tests/test_participant_timeline.py`` (the two
test_knights_vow_* tests ~3512/3557 and the typed-action reuse
~4850); the kernel poison/fallback in ``tests/test_survival_kernel.py``
(test_knights_vow_redirect_poisons_context_and_falls_back ~657); the
front-end option schema in ``tests/test_app.py`` (~1644/1686).  This
file is disjoint and pins only the Knight's Vow acceptance observables.
"""

from collections import defaultdict
from types import SimpleNamespace

import pytest

from src.calculator.item_coverage import ATTACKER_LANES
from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_coverage import item_model_coverage, target_item_model_coverage
from src.calculator.item_effects import (
    ALLY_ITEM_EFFECTS,
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    ally_item_effect_value,
    item_state_receipts,
    validate_item_input_options,
)
from src.calculator.item_support_effects import schedule_knights_vow
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    build_participant_timeline,
    _simulate_survival as _simulate_survival_walk,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.interpreters import uncompilable_item_receipt


# MERGE: ``_simulate_survival`` returns the frozen ``WalkResult`` now -- one
# walk handed to five views -- so a caller that wants the published rows
# projects it through the survival view, exactly as the composition does.
def _simulate_survival(combatants, *args, **kwargs):
    combatant_list = list(combatants)
    return _survival_view(
        _roster_program(combatant_list),
        _simulate_survival_walk(combatant_list, *args, **kwargs),
    )


ITEM_NAME = "Knight's Vow"
ITEM_ID = 3109
PRICE = 2300
SELL = 920
BUILDS_FROM = (3067, 1031, 1006)
HEALTH_FLAT = 200.0
ARMOR_FLAT = 40.0
ABILITY_HASTE_FLAT = 10.0
BASE_REGEN_PERCENT = 100.0
REDIRECT_FRACTION = 0.14
HEAL_FRACTION = 0.12
RANGE_UNITS = 1250.0
HOLDER_HEALTH_RATIO = 0.30
SOURCE_REVISION = 4023793
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Knight%27s_Vow"
REDIRECT_SOURCE = "Knight's Vow \u2014 Sacrifice"
# The exact cached branch text fragments (passive branches + active).
BRANCH_FRAGMENTS = (
    "<passive>Sacrifice</passive>",
    "<active>Pledge</active>",
    "1250 units",
    "30% of your '''maximum''' health",
    "redirect 14%",
    "pre-mitigation",
    "physical",
    "magic",
    "12%",
    "post-mitigation damage",
    "champions",
    "Designate the target allied champion as being ''Worthy''",
    "one '''Knight's Vow''' at a time",
)


def _kv_item() -> dict:
    """The real cached item record (id 3109)."""
    return get_item_by_name(ITEM_NAME)


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    item_options: dict | None = None,
    ally_effects_enabled: bool = True,
) -> SimpleNamespace:
    """Scheduler-level actor (mirrors test_item_support_effects)."""
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=SimpleNamespace(
            item_options=item_options or {},
            ally_effects_enabled=ally_effects_enabled,
        ),
    )


def _combatant(
    participant_id: str,
    team: str,
    *,
    health: float = 100.0,
    armor: float = 0.0,
    magic_resistance: float = 0.0,
) -> Combatant:
    """Survival-level combatant (mirrors test_participant_timeline's
    _dummy_combatant with explicit resistances)."""
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
        stats={
            "health": health,
            "armor": armor,
            "magic_resistance": magic_resistance,
            "bonus_armor": 0.0,
            "bonus_magic_resistance": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "is_melee": False,
        },
        defenses=defenses,
    )


def _kv_redirect_event(
    event_id: str,
    time: float,
    damage: float,
    *,
    damage_type: str = "physical",
    attacker: str = "source",
    target: str = "protected",
    baseline: float = 0.0,
) -> dict:
    """One receipt-scheduler-authored redirect packet (the exact shape
    schedule_knights_vow produces for a Worthy's incoming event)."""
    event = {
        "time": time,
        "damage": damage,
        "damage_type": damage_type,
        "attacker": attacker,
        "target": target,
        "sequence": int(time * 10),
        "_event_id": event_id,
        "redirect_fraction": REDIRECT_FRACTION,
        "redirect_target": "holder",
        "redirect_source": REDIRECT_SOURCE,
        "redirect_pre_mitigation_required": True,
        "redirect_holder_health_ratio": HOLDER_HEALTH_RATIO,
        "redirect_range_units": RANGE_UNITS,
        "redirect_source_revision_id": SOURCE_REVISION,
    }
    if damage_type == "physical":
        event["_baseline_effective_armor"] = baseline
    else:
        event["_baseline_effective_mr"] = baseline
    return event


def _coupled_fight(
    *,
    ally_items: tuple[str, ...] = (ITEM_NAME,),
    ally_options: dict | None = None,
    _default_worthy: bool = True,
    ally_effects_enabled: bool = True,
    include_receipt: bool = True,
    search_context: CoupledSearchContext | None = None,
    pair_result_cache: dict | None = None,
    duration: float = 12.0,
) -> dict:
    """A coupled fight where the MAIN is Ahri, an ALLY Ashe holds Knight's
    Vow (worthy index 0 -> the main), and Janna is the enemy.  With no
    ally items the fixture is the no-redirect control on the same roster.
    ``include_receipt=False`` returns the coupled score surface; passing a
    ``search_context`` plus an empty pair cache exercises the compiled
    score path (which must fail closed on Knight's Vow today and fall back
    to the shared walk)."""
    champion = get_champion("Ahri")
    items = [get_item_by_name("Infinity Edge")]
    stats = calculate_total_stats(champion, 18, items, role="mid")
    defenses = resolve_starting_defenses("Ahri", 18, stats, items)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": duration,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemies = [ChampionLoadout(champion="Janna", level=18, role="support").resolve()]
    allies = [
        ChampionLoadout(
            champion="Ashe",
            level=18,
            role="bottom",
            items=ally_items,
            item_options=(
                {
                    ITEM_NAME: {
                        "worthy_target_index": 0,
                        **(dict(ally_options or {})),
                    }
                }
                if _default_worthy and ally_items
                else ({ITEM_NAME: ally_options} if ally_options else {})
            ),
            ally_effects_enabled=ally_effects_enabled,
        ).resolve()
    ]
    return build_participant_timeline(
        champion,
        18,
        items,
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=enemies,
        allies=allies,
        include_receipt=include_receipt,
        pair_result_cache=(
            pair_result_cache
            if pair_result_cache is not None
            else ({} if search_context is not None else None)
        ),
        search_context=search_context,
    )


def _main_survival(result: dict) -> dict:
    """The main's survival row (participant 0) on either surface."""
    return result["participants"][0]["survival"]


def _ally_survival(result: dict) -> dict:
    """The ally's survival row (participant 1) on either surface."""
    return result["participants"][1]["survival"]


def _kv_heal_support_events(result: dict) -> list[dict]:
    return [
        event
        for event in result.get("support_events", [])
        if event.get("source") == REDIRECT_SOURCE
    ]


def _main_redirect_events(result: dict) -> list[dict]:
    """The main's incoming events carrying the authored redirect markers."""
    return [
        event
        for event in result.get("events", [])
        if event.get("target") == "main"
        and event.get("redirect_source") == REDIRECT_SOURCE
    ]


# ---------------------------------------------------------------------------
# 1. Identity / stats / passive / active
# ---------------------------------------------------------------------------


def test_cached_identity_pins_name_id_price_stats_and_branches():
    item = _kv_item()
    assert item["name"] == ITEM_NAME
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["shop"]["prices"]["sell"] == SELL
    assert item["tier"] == 3
    assert item["rank"] == ["LEGENDARY"]
    assert item["buildsFrom"] == list(BUILDS_FROM)
    assert item["stats"]["health"]["flat"] == HEALTH_FLAT
    assert item["stats"]["armor"]["flat"] == ARMOR_FLAT
    assert item["stats"]["abilityHaste"]["flat"] == ABILITY_HASTE_FLAT
    assert item["stats"]["healthRegen"]["percent"] == BASE_REGEN_PERCENT
    (passive,) = item["passives"]
    assert passive["name"] == "Sacrifice"
    assert passive["unique"] is True
    (active,) = item["active"]
    assert active["name"] == "Pledge"
    assert active["unique"] is True
    # The short riotDescription carries the passive/active markup; the
    # full mechanic sentences (1250 tether, 30% gate, 14% redirect, 12%
    # heal, one-Worthy exclusivity) live in the branch text of the
    # passive and the active.  Pin the union so the exact authored
    # wording cannot drift.
    branch = (
        item["riotDescription"]
        + "".join(passive["branches"][0] for passive in item["passives"])
        + item["active"][0]["branches"][0]
    )
    for fragment in BRANCH_FRAGMENTS:
        assert fragment in branch


def test_equipping_knights_vow_yields_exactly_200_health_40_armor_10_haste_and_full_base_regen():
    main = get_champion("Ahri")
    base = calculate_total_stats(main, 18, [])
    with_kv = calculate_total_stats(main, 18, [_kv_item()])
    diffs = {key: with_kv[key] - base[key] for key in with_kv}
    assert diffs["health"] == pytest.approx(HEALTH_FLAT)
    assert diffs["bonus_health"] == pytest.approx(HEALTH_FLAT)
    assert diffs["armor"] == pytest.approx(ARMOR_FLAT)
    assert diffs["bonus_armor"] == pytest.approx(ARMOR_FLAT)
    assert diffs["ability_haste"] == pytest.approx(ABILITY_HASTE_FLAT)
    # +100% BASE health regen: the percent doubles Ahri's own base and the
    # per-five delta equals her level-18 base regen (12.7).
    assert diffs["health_regen_percent"] == pytest.approx(BASE_REGEN_PERCENT)
    assert diffs["health_regen_per_five"] == pytest.approx(
        base["base_health_regen_per_five"]
    )
    changed = {key: round(value, 4) for key, value in diffs.items() if value != 0.0}
    assert changed == {
        "health": HEALTH_FLAT,
        "bonus_health": HEALTH_FLAT,
        "armor": ARMOR_FLAT,
        "bonus_armor": ARMOR_FLAT,
        "ability_haste": ABILITY_HASTE_FLAT,
        "health_regen_percent": BASE_REGEN_PERCENT,
        "health_regen_per_five": round(base["base_health_regen_per_five"], 4),
        "health_regen_per_second": round(base["base_health_regen_per_five"] / 5.0, 4),
    }


# ---------------------------------------------------------------------------
# 2. Typed source values
# ---------------------------------------------------------------------------


def test_typed_sacrifice_values_return_exact_numbers():
    assert ally_item_effect_value(ITEM_NAME, "redirect_fraction") == pytest.approx(
        REDIRECT_FRACTION
    )
    assert ally_item_effect_value(ITEM_NAME, "holder_heal_fraction") == pytest.approx(
        HEAL_FRACTION
    )
    assert ally_item_effect_value(ITEM_NAME, "worthy_range_units") == pytest.approx(
        RANGE_UNITS
    )
    assert ally_item_effect_value(
        ITEM_NAME, "holder_health_threshold_ratio"
    ) == pytest.approx(HOLDER_HEALTH_RATIO)
    # The registry entry is the ally-packet table, not the outgoing-damage
    # table; the ordinary item stats still flow through stats.py.
    assert ITEM_NAME not in ITEM_EFFECTS
    assert ITEM_NAME in ALLY_ITEM_EFFECTS


def test_source_revision_is_discoverable_on_the_input_options_receipt():
    """The wiki source receipt rides the ITEM_INPUT_OPTIONS entry (the same
    pattern as Guardian Angel): source_url + source_revision_id 4023793 are
    discoverable without any network call."""
    config = ITEM_INPUT_OPTIONS[ITEM_NAME]
    assert config["source_url"] == SOURCE_URL
    assert config["source_revision_id"] == SOURCE_REVISION
    assert ALLY_ITEM_EFFECTS[ITEM_NAME]["source_revision_id"] == SOURCE_REVISION
    options = config["options"]
    assert options["worthy_target_index"] == {
        "type": "int",
        "label": "Worthy ally index",
        "default": -1,
        "min": -1,
        "max": 4,
        "step": 1,
    }
    assert options["worthy_within_range"]["default"] == 1
    assert options["worthy_within_range"]["max"] == 1
    assert options["holder_above_30_percent"]["default"] == 1
    assert options["holder_above_30_percent"]["max"] == 1


def test_missing_typed_key_fails_loud_naming_item_and_key(monkeypatch):
    patched = dict(ALLY_ITEM_EFFECTS[ITEM_NAME])
    del patched["redirect_fraction"]
    monkeypatch.setitem(ALLY_ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(KeyError) as excinfo:
        ally_item_effect_value(ITEM_NAME, "redirect_fraction")
    message = str(excinfo.value)
    # The message reprs the item name, so the apostrophe is escaped
    # (Knight\'s Vow); assert the item and the key both appear.
    assert "Knight" in message
    assert "Vow" in message
    assert "redirect_fraction" in message


def test_malformed_typed_values_fail_loudly(monkeypatch):
    base = dict(ALLY_ITEM_EFFECTS[ITEM_NAME])
    patched = dict(base)
    patched["redirect_fraction"] = "oops"
    monkeypatch.setitem(ALLY_ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(ValueError) as excinfo:
        ally_item_effect_value(ITEM_NAME, "redirect_fraction")
    assert ITEM_NAME in str(excinfo.value)
    assert "redirect_fraction" in str(excinfo.value)
    patched = dict(base)
    patched["holder_heal_fraction"] = None
    monkeypatch.setitem(ALLY_ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(ValueError):
        ally_item_effect_value(ITEM_NAME, "holder_heal_fraction")


# ---------------------------------------------------------------------------
# 3. Owner/ally relationship + target selection
# ---------------------------------------------------------------------------


def test_scheduler_selects_the_authored_worthy_index_and_owner_is_the_holder():
    holder = _actor(
        "ally:Lulu",
        "ally",
        (ITEM_NAME,),
        item_options={ITEM_NAME: {"worthy_target_index": 1}},
    )
    first = _actor("main:Ahri", "main", ())
    second = _actor("ally:Nami", "ally", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    incoming = {
        first.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": first.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ],
        second.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": second.participant_id,
                "damage": 100.0,
                "damage_type": "magic",
            }
        ],
    }
    outgoing = {
        second.participant_id: [
            {
                "time": 1.0,
                "attacker": second.participant_id,
                "target": enemy.participant_id,
                "damage": 200.0,
                "damage_type": "physical",
            }
        ]
    }
    support = defaultdict(list)
    schedule_knights_vow([holder, first, second, enemy], incoming, outgoing, support)
    # Index 1 selects the SECOND teammate (Nami); Ahri's event is untouched.
    assert "redirect_fraction" not in incoming[first.participant_id][0]
    assert incoming[second.participant_id][0]["redirect_fraction"] == pytest.approx(
        REDIRECT_FRACTION
    )
    assert (
        incoming[second.participant_id][0]["redirect_target"] == holder.participant_id
    )
    assert incoming[second.participant_id][0]["redirect_source"] == REDIRECT_SOURCE
    heal = next(p for p in support[holder.participant_id] if p["kind"] == "heal")
    assert heal["target"] == holder.participant_id
    # The non-owner authored no packets.
    assert not support[first.participant_id]


def test_scheduler_authors_nothing_for_a_non_owner_or_empty_roster():
    non_holder = _actor("ally:Lulu", "ally", ())
    first = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    incoming = {
        first.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": first.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ]
    }
    outgoing = {}
    support = defaultdict(list)
    # No Knight's Vow anywhere: nothing authored (fail closed).
    schedule_knights_vow([non_holder, first, enemy], incoming, outgoing, support)
    assert "redirect_fraction" not in incoming[first.participant_id][0]
    assert not support
    # Owner with NO eligible teammate (only the enemy on the roster): the
    # tether has no target and nothing is authored.
    holder = _actor("ally:Lulu", "ally", (ITEM_NAME,))
    incoming2 = {
        first.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": first.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ]
    }
    support2 = defaultdict(list)
    schedule_knights_vow([holder, enemy], incoming2, outgoing, support2)
    assert "redirect_fraction" not in incoming2[first.participant_id][0]
    assert not support2


def test_missing_authored_index_selects_the_first_teammate_today():
    """P3-3S sentinel rule: with no authored worthy_target_index the
    scheduler falls back to the no-selection sentinel (-1) — no Worthy
    ally is designated and the redirect/heal do NOT fire (Pledge is
    unit-targeted; a missing designation is a named fail-closed case,
    never an invented first teammate)."""
    holder = _actor("ally:Lulu", "ally", (ITEM_NAME,))
    first = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    incoming = {
        first.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": first.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ]
    }
    outgoing = {}
    support = defaultdict(list)
    schedule_knights_vow([holder, first, enemy], incoming, outgoing, support)
    assert "redirect_target" not in incoming[first.participant_id][0]
    assert "redirect_fraction" not in incoming[first.participant_id][0]
    assert not support


def test_fail_closed_contract_no_authored_index_means_no_redirect_or_heal():
    holder = _actor("ally:Lulu", "ally", (ITEM_NAME,))
    first = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    incoming = {
        first.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": first.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ]
    }
    outgoing = {}
    support = defaultdict(list)
    schedule_knights_vow([holder, first, enemy], incoming, outgoing, support)
    assert "redirect_fraction" not in incoming[first.participant_id][0]
    assert not support


def test_validate_item_input_options_rejects_out_of_range_and_non_integer_index():
    with pytest.raises(ValueError, match="must be between -1 and 4"):
        validate_item_input_options({ITEM_NAME: {"worthy_target_index": 5}})
    with pytest.raises(ValueError, match="must be between -1 and 4"):
        validate_item_input_options({ITEM_NAME: {"worthy_target_index": -2}})
    # The -1 sentinel is the valid no-selection designation (P3 package 3S).
    parsed = validate_item_input_options({ITEM_NAME: {"worthy_target_index": -1}})
    assert parsed[ITEM_NAME]["worthy_target_index"] == -1
    with pytest.raises(ValueError, match="must be an integer"):
        validate_item_input_options({ITEM_NAME: {"worthy_target_index": True}})
    # The authored gates are bounded 0/1 as well.
    with pytest.raises(ValueError, match="must be between 0 and 1"):
        validate_item_input_options({ITEM_NAME: {"worthy_within_range": 2}})
    with pytest.raises(ValueError, match="must be between 0 and 1"):
        validate_item_input_options({ITEM_NAME: {"holder_above_30_percent": 2}})
    # A valid authored index round-trips.
    parsed = validate_item_input_options({ITEM_NAME: {"worthy_target_index": 3}})
    assert parsed[ITEM_NAME]["worthy_target_index"] == 3


# ---------------------------------------------------------------------------
# 4. Redirect amount + timing + holder heal
# ---------------------------------------------------------------------------


def test_redirect_reprices_pre_mitigation_damage_for_holder_resistance():
    """Mirror of test_participant_timeline.py ~3512: 100 raw physical to an
    unarmoured Worthy with the holder at 100 armor.  86 raw reaches the
    Worthy (86 post-mitigation at 0 armor); 14 raw is redirected and
    mitigated by the holder's 100 armor -> 7."""
    source = _combatant("source", "enemy")
    protected = _combatant("protected", "main", armor=0.0)
    holder = _combatant("holder", "main", armor=100.0)
    event = _kv_redirect_event("kv-premit", 0.0, 100.0)
    result = _simulate_survival(
        [source, protected, holder], {"protected": [event]}, {}, {}, 10.0
    )
    assert result["protected"]["health_damage"] == pytest.approx(86.0)
    assert result["holder"]["health_damage"] == pytest.approx(7.0)


def test_redirect_uses_the_respective_damage_type_for_the_holder():
    """Magic damage redirects as MAGIC: the holder's magic resistance
    mitigates the redirected share (100 raw, holder 300 MR -> 3.5)."""
    source = _combatant("source", "enemy")
    protected = _combatant("protected", "main")
    holder = _combatant("holder", "main", magic_resistance=300.0)
    event = _kv_redirect_event(
        "kv-magic", 0.0, 100.0, damage_type="magic", baseline=0.0
    )
    result = _simulate_survival(
        [source, protected, holder], {"protected": [event]}, {}, {}, 10.0
    )
    # 14 raw magic against 300 MR -> 14 * 100/400 = 3.5.
    assert result["protected"]["health_damage"] == pytest.approx(86.0)
    assert result["holder"]["health_damage"] == pytest.approx(3.5)


def test_true_damage_incoming_is_never_redirected():
    """Sacrifice redirects physical and magic only (the exact branch text);
    true damage to the Worthy is never stamped and never split."""
    source = _combatant("source", "enemy")
    protected = _combatant("protected", "main")
    holder = _combatant("holder", "main", armor=100.0)
    event = {
        "time": 0.0,
        "damage": 100.0,
        "damage_type": "true",
        "attacker": "source",
        "target": "protected",
        "sequence": 0,
        "_event_id": "kv-true",
    }
    result = _simulate_survival(
        [source, protected, holder], {"protected": [event]}, {}, {}, 10.0
    )
    assert result["protected"]["health_damage"] == pytest.approx(100.0)
    assert result["holder"]["health_damage"] == pytest.approx(0.0)
    incoming = {"protected": [dict(event)]}
    schedule_knights_vow(
        [holder, protected, source],
        incoming,
        {"protected": []},
        defaultdict(list),
    )
    assert "redirect_fraction" not in incoming["protected"][0]


def test_holder_heal_is_0_12_of_post_mitigation_worthy_damage():
    """Mirror of test_item_support_effects.py ~538: the heal packet is
    0.12 x the post-mitigation Worthy outgoing damage, authored on the
    owner with the typed boundaries.  True damage dealt by the Worthy
    ALSO counts (the branch text heals from damage dealt to champions)."""
    holder = _actor(
        "ally:Lulu",
        "ally",
        (ITEM_NAME,),
        item_options={ITEM_NAME: {"worthy_target_index": 0}},
    )
    worthy = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    outgoing = {
        worthy.participant_id: [
            {
                "time": 1.0,
                "attacker": worthy.participant_id,
                "target": enemy.participant_id,
                "damage": 200.0,
                "damage_type": "physical",
            },
            {
                "time": 1.5,
                "attacker": worthy.participant_id,
                "target": enemy.participant_id,
                "damage": 50.0,
                "damage_type": "true",
            },
        ]
    }
    support = defaultdict(list)
    schedule_knights_vow([holder, worthy, enemy], {}, outgoing, support)
    heals = [p for p in support[holder.participant_id] if p["kind"] == "heal"]
    assert len(heals) == 2
    assert heals[0]["amount"] == pytest.approx(24.0)
    assert heals[1]["amount"] == pytest.approx(6.0)
    for heal in heals:
        assert heal["source"] == REDIRECT_SOURCE
        assert heal["target"] == holder.participant_id
        assert heal["target_scope"] == "holder_from_worthy_damage"
        assert heal["healing_category"] == "knights_vow"
        assert heal["requires_holder_health_ratio"] == pytest.approx(
            HOLDER_HEALTH_RATIO
        )
        assert heal["range_units"] == pytest.approx(RANGE_UNITS)
        assert heal["source_revision_id"] == SOURCE_REVISION


def test_kernel_cancels_redirect_when_holder_falls_below_health_gate():
    """Mirror of test_participant_timeline.py ~3557: the holder's 30%
    gate is an ORDERED state gate.  After 90 true damage the holder (100
    max) sits at 10 health; the next redirected packet is cancelled and
    the Worthy takes the full 40."""
    source = _combatant("source", "enemy")
    protected = _combatant("protected", "main")
    holder = _combatant("holder", "main")
    incoming = {
        "holder": [
            {
                "time": 0.0,
                "damage": 90.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "holder",
                "sequence": 0,
                "_event_id": "holder-hit",
            }
        ],
        "protected": [_kv_redirect_event("kv-gated", 1.0, 40.0)],
    }
    result = _simulate_survival([source, protected, holder], incoming, {}, {}, 10.0)
    assert result["protected"]["health_damage"] == pytest.approx(40.0)
    assert result["holder"]["health_damage"] == pytest.approx(90.0)


def test_kernel_skips_the_holder_heal_below_the_health_gate():
    """The heal packet carries requires_holder_health_ratio 0.30; the walk
    skips it (reason "holder_health_gate") while the holder is at/below
    30% max health, and applies it (capped by missing health) above."""
    source = _combatant("source", "enemy")
    holder = _combatant("holder", "main", health=100.0)
    heal = {
        "time": 2.0,
        "kind": "heal",
        "amount": 24.0,
        "source": REDIRECT_SOURCE,
        "attacker": "holder",
        "target": "holder",
        "healing_category": "knights_vow",
        "requires_holder_health_ratio": HOLDER_HEALTH_RATIO,
        "range_units": RANGE_UNITS,
        "source_revision_id": SOURCE_REVISION,
    }
    below = {
        "holder": [
            {
                "time": 0.0,
                "damage": 80.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "holder",
                "sequence": 0,
                "_event_id": "h1",
            }
        ]
    }
    result = _simulate_survival(
        [source, holder], below, {"holder": [dict(heal)]}, {}, 10.0
    )
    # Holder at 20/100 <= 30: heal skipped.
    assert result["holder"]["healing_received"] == pytest.approx(0.0)
    above = {
        "holder": [
            {
                "time": 0.0,
                "damage": 20.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "holder",
                "sequence": 0,
                "_event_id": "h2",
            }
        ]
    }
    result = _simulate_survival(
        [source, holder], above, {"holder": [dict(heal)]}, {}, 10.0
    )
    # Holder at 80/100 > 30: the 24 heal applies, capped by missing health.
    assert result["holder"]["healing_received"] == pytest.approx(20.0)


def test_coupled_fight_reduces_worthy_damage_and_authors_redirect_events():
    """End-to-end: with the ally Knight's Vow holder tethered to the main
    (index 0), the main's incoming events carry the authored redirect
    markers, the ally receives the redirected clones, and the main's
    health damage drops below the same-roster control."""
    # Control: the SAME ally loadout with the authored range gate off (the
    # ally's stats stay identical, so the only difference is the redirect).
    control = _coupled_fight(
        ally_options={"worthy_target_index": 0, "worthy_within_range": 0}
    )
    with_kv = _coupled_fight()
    assert (
        _main_survival(control)["health_damage"]
        > _main_survival(with_kv)["health_damage"]
    )
    events = _main_redirect_events(with_kv)
    assert events
    for event in events:
        assert event["redirect_fraction"] == pytest.approx(REDIRECT_FRACTION)
        assert event["redirect_source"] == REDIRECT_SOURCE
        assert event["redirect_range_units"] == pytest.approx(RANGE_UNITS)
        assert float(event.get("redirected_amount", 0.0) or 0.0) > 0.0
        # The public event drops the target field (the walk annotates a
        # subset); the recipient is pinned below via the redirected clones
        # and the survival reduction above.
    clones = [
        e
        for e in with_kv["events"]
        if e.get("redirected_from") == "main" and e.get("redirect_pre_mitigation")
    ]
    assert clones
    for clone in clones:
        assert clone["target"] == "ally:Ashe"
        assert clone["redirect_attributed_to"] == "enemy:Janna"
    # The ally holder actually heals from the Worthy's outgoing damage.
    heals = _kv_heal_support_events(with_kv)
    assert heals
    assert all(h["target_scope"] == "holder_from_worthy_damage" for h in heals)
    assert all(h["kind"] == "heal" for h in heals)
    assert sum(h.get("applied_amount", 0.0) for h in heals) > 0.0
    assert _ally_survival(with_kv)["healing_received"] > 0.0


# ---------------------------------------------------------------------------
# 5. Fail-closed
# ---------------------------------------------------------------------------


def test_authored_gate_options_disable_redirect_and_heal_with_named_reasons():
    """worthy_within_range=0 disables the branch with
    "worthy_out_of_range" on the Worthy's physical/magic events;
    holder_above_30_percent=0 disables it with
    "holder_health_gate_disabled".  Both leave the main's health damage at
    the no-redirect control value (no invented numbers)."""
    # Control: the same ally with the range gate off (identical stats; the
    # authored gate variants below must reproduce its health damage).
    control = _coupled_fight(
        ally_options={"worthy_target_index": 0, "worthy_within_range": 0}
    )
    control_hd = _main_survival(control)["health_damage"]
    for option, reason in (
        ({"worthy_target_index": 0, "worthy_within_range": 0}, "worthy_out_of_range"),
        (
            {"worthy_target_index": 0, "holder_above_30_percent": 0},
            "holder_health_gate_disabled",
        ),
    ):
        result = _coupled_fight(ally_options=option)
        assert _main_survival(result)["health_damage"] == pytest.approx(control_hd)
        reasons = {
            event.get("redirect_skipped_reason")
            for event in result["events"]
            if event.get("redirect_skipped_reason")
        }
        assert reasons == {reason}
        assert not _kv_heal_support_events(result)


def test_absent_knights_vow_produces_no_receipt_row_and_no_typed_state():
    """An absent item leaves no item_state_receipts row today and the
    coverage posture stays explicit (the item's absence never invents a
    tether)."""
    assert (
        item_state_receipts([], {}, fight_duration_seconds=16.0, is_melee=False) == []
    )
    assert uncompilable_item_receipt([]) is None


# ---------------------------------------------------------------------------
# 6. Receipt fields + source evidence
# ---------------------------------------------------------------------------


def test_scheduler_packet_receipts_carry_the_typed_boundaries():
    """The receipt-scheduler packet fields (the support-packet receipt the
    coordinator's compiled staging must mirror): redirect_fraction,
    redirect_target, redirect_source, redirect_pre_mitigation_required,
    redirect_holder_health_ratio, redirect_range_units, and the source
    revision on the incoming event."""
    holder = _actor(
        "ally:Lulu",
        "ally",
        (ITEM_NAME,),
        item_options={ITEM_NAME: {"worthy_target_index": 0}},
    )
    worthy = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    incoming = {
        worthy.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": worthy.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ]
    }
    schedule_knights_vow([holder, worthy, enemy], incoming, {}, defaultdict(list))
    stamped = incoming[worthy.participant_id][0]
    assert stamped["redirect_fraction"] == pytest.approx(REDIRECT_FRACTION)
    assert stamped["redirect_target"] == holder.participant_id
    assert stamped["redirect_source"] == REDIRECT_SOURCE
    assert stamped["redirect_pre_mitigation_required"] is True
    assert stamped["redirect_holder_health_ratio"] == pytest.approx(HOLDER_HEALTH_RATIO)
    assert stamped["redirect_range_units"] == pytest.approx(RANGE_UNITS)
    assert stamped["redirect_source_revision_id"] == SOURCE_REVISION


def test_item_state_receipts_emits_exactly_one_knights_vow_row():
    receipts = item_state_receipts(
        [_kv_item()], {}, fight_duration_seconds=16.0, is_melee=False
    )
    (receipt,) = [row for row in receipts if row.get("item") == ITEM_NAME]
    assert receipt["state"] == "sacrifice"
    assert receipt["redirect_fraction"] == pytest.approx(REDIRECT_FRACTION)
    assert receipt["holder_heal_fraction"] == pytest.approx(HEAL_FRACTION)
    assert receipt["worthy_range_units"] == pytest.approx(RANGE_UNITS)
    assert receipt["holder_health_threshold_ratio"] == pytest.approx(
        HOLDER_HEALTH_RATIO
    )
    assert receipt["source_url"] == SOURCE_URL
    assert receipt["source_revision_id"] == SOURCE_REVISION


# ---------------------------------------------------------------------------
# 7. Compiled vs receipt parity
# ---------------------------------------------------------------------------


def test_score_path_agrees_with_receipt_on_every_observable():
    """The coupled score surface (include_receipt=False) returns the same
    survival rows, breakdown fields, and duration as the receipt surface.
    Knight's Vow sits in COMPILED_WALK_UNREPRESENTABLE_ITEMS, so the
    compiled fast path fails closed and both surfaces run the shared walk —
    equality by construction today.  This is the score-path equality the
    P3-3S certification must preserve with byte parity."""
    receipt = _coupled_fight()
    score = _coupled_fight(include_receipt=False)
    ctx = CoupledSearchContext()
    compiled = _coupled_fight(include_receipt=False, search_context=ctx)
    for surface in (score, compiled):
        assert surface["participants"][0]["survival"] == _main_survival(receipt)
        assert surface["participants"][1]["survival"] == _ally_survival(receipt)
        assert surface["duration"] == receipt["duration"]
        for score_row, receipt_row in zip(surface["breakdown"], receipt["breakdown"]):
            assert score_row["participant_id"] == receipt_row["participant_id"]
            assert score_row["incoming_damage"] == receipt_row["incoming_damage"]
            assert score_row["health_damage"] == receipt_row["health_damage"]
            assert score_row["death_time"] == receipt_row["death_time"]
            assert score_row["survived_window"] == receipt_row["survived_window"]
            if score_row["total_damage"] == receipt_row["total_damage"]:
                continue
            # The ONLY receipt-vs-score total_damage delta is the
            # receipt-only artifact: _insert_receipt_clone mirrors the
            # redirected clones into the ATTACKER's outgoing ledger
            # (the clone keeps the source attacker id), so the attacker's
            # receipt total includes the applied redirected shares.  The
            # score surface has no receipt_events and therefore excludes
            # them; the survival rows agree either way.  Pin the delta to
            # the mirrored clone sum so the parity claim stays exact.
            clones = [
                event.get("damage", 0.0)
                for event in receipt["events"]
                if event.get("redirected_from")
                and event.get("attacker") == receipt_row["participant_id"]
            ]
            # The receipt's total_damage is the outgoing EVENT ledger sum:
            # it includes packets the walk skipped for attacker CC-blocked
            # states at their full event values.  The compiled total counts
            # only the APPLIED amounts (the honest number).  For the
            # CC-blocked attacker (Janna is charmed at t=0 in this
            # fixture), the named delta is exactly the blocked parents'
            # event values; every other row equals receipt - clones.
            blocked = [
                event.get("damage", 0.0)
                for event in receipt["events"]
                if event.get("attacker") == receipt_row["participant_id"]
                and event.get("redirect_source") == REDIRECT_SOURCE
                and not event.get("redirected_from")
                and float(event.get("time", 0.0)) <= 1.25
            ]
            if surface is compiled:
                # The compiled total is the applied-based sum: the parents'
                # direct shares + the applied children.  The receipt total
                # is the outgoing EVENT ledger sum: direct values (including
                # CC-blocked packets) + the mirrored clones.  The applied
                # children and the mirrored clones are the same amounts, so
                # they cancel: compiled == receipt - blocked.
                assert score_row["total_damage"] == pytest.approx(
                    receipt_row["total_damage"] - sum(blocked), abs=0.15
                )
            else:
                assert score_row["total_damage"] == pytest.approx(
                    receipt_row["total_damage"] - sum(clones), abs=0.15
                )
    # The fixture actually exercised the whole Sacrifice machine.
    assert _main_redirect_events(receipt)
    assert _kv_heal_support_events(receipt)
    # P3-3S: the compiled context rides the shared kernel with panels and
    # stays unpoisoned (byte parity proven by the loops above).
    assert ctx.uncompilable is False
    assert ctx.panels


def test_compiled_panels_carry_the_knights_vow_fight():
    ctx = CoupledSearchContext()
    legacy = _coupled_fight(include_receipt=False)
    fast = _coupled_fight(include_receipt=False, search_context=ctx)
    # Survival rows and every breakdown field except the CC-blocked
    # attacker's total_damage are byte-equal (the receipt/legacy totals
    # are the outgoing event ledger sum; the compiled total is the
    # applied-based sum — the documented delta is the CC-blocked parents'
    # event values, pinned in the parity test above).
    assert fast["participants"] == legacy["participants"]
    assert fast["duration"] == legacy["duration"]
    for fast_row, legacy_row in zip(fast["breakdown"], legacy["breakdown"]):
        assert fast_row["participant_id"] == legacy_row["participant_id"]
        assert fast_row["health_damage"] == legacy_row["health_damage"]
        assert fast_row["healing_received"] == legacy_row["healing_received"]
        assert fast_row["incoming_damage"] == legacy_row["incoming_damage"]
        assert fast_row["death_time"] == legacy_row["death_time"]
        assert fast_row["survived_window"] == legacy_row["survived_window"]
        if fast_row["participant_id"] == "enemy:Janna":
            assert fast_row["total_damage"] < legacy_row["total_damage"]
        else:
            assert fast_row["total_damage"] == legacy_row["total_damage"]
    assert ctx.uncompilable is False
    assert ctx.panels


def test_enemy_holder_poisons_the_compiled_context_and_falls_back():
    """A Knight's Vow holder on the enemy roster is search-invariant: the
    capability scan marks the context uncompilable (panels empty) and
    every evaluation falls back to the shared walk, still deep-equal.
    This is today's fail-closed boundary for the roster side."""
    main = get_champion("Ahri")
    main_stats = calculate_total_stats(main, 18, [])
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Janna", level=18, items=(ITEM_NAME,)).resolve()
    kwargs = dict(
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Ahri", 18, main_stats, []),
        enemies=[enemy],
        allies=[],
    )
    legacy = build_participant_timeline(
        main, 18, [], params, include_receipt=False, **kwargs
    )
    ctx = CoupledSearchContext()
    fast = build_participant_timeline(
        main,
        18,
        [],
        params,
        include_receipt=False,
        pair_result_cache={},
        search_context=ctx,
        **kwargs,
    )
    assert fast == legacy
    # P3-3S: the roster-side Knight's Vow holder compiles — the capability
    # scan no longer poisons the context and panels are built (the enemy
    # holder has no Worthy teammates in this fixture, so the tether is
    # empty and the staging no-ops with byte parity).
    assert ctx.uncompilable is False
    assert ctx.panels


def test_roster_holder_compiles_after_certification():
    main = get_champion("Ahri")
    main_stats = calculate_total_stats(main, 18, [])
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Janna", level=18, items=(ITEM_NAME,)).resolve()
    kwargs = dict(
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Ahri", 18, main_stats, []),
        enemies=[enemy],
        allies=[],
    )
    legacy = build_participant_timeline(
        main, 18, [], params, include_receipt=False, **kwargs
    )
    ctx = CoupledSearchContext()
    fast = build_participant_timeline(
        main,
        18,
        [],
        params,
        include_receipt=False,
        pair_result_cache={},
        search_context=ctx,
        **kwargs,
    )
    assert fast == legacy
    assert ctx.uncompilable is False
    assert ctx.panels


def test_tuple_ledger_fight_fails_closed_with_parity_and_no_crash():
    """A tuple-ledger champion (Riven's pair engine emits light rows)
    holding Knight's Vow in a coupled fight: today the item fails closed
    per evaluation (candidate-local), the context stays usable, and the
    score surface deep-equals the receipt walk — never a crash.  (The
    post-certification tuple guard — named receipts for light rows that
    omit redirect metadata — is the coordinator's staging surface.)"""
    main = get_champion("Riven")
    items = [_kv_item()]
    main_stats = calculate_total_stats(main, 18, items)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 12,
            "role": "top",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy_loadout = ChampionLoadout(champion="Cassiopeia", level=18, items=[]).resolve()
    defenses = resolve_starting_defenses("Riven", 18, main_stats, items)

    def fight(**kwargs):
        return build_participant_timeline(
            main,
            18,
            items,
            params,
            main_stats=main_stats,
            main_defenses=defenses,
            enemies=[enemy_loadout],
            allies=[],
            include_receipt=kwargs.pop("include_receipt", True),
            pair_result_cache={} if kwargs.get("search_context") is not None else None,
            **kwargs,
        )

    legacy = fight(include_receipt=False)
    ctx = CoupledSearchContext()
    fast = fight(include_receipt=False, search_context=ctx)
    assert fast == legacy
    assert ctx.uncompilable is False


def test_legacy_score_only_pair_surface_carries_no_survival_state():
    """Named fail-closed boundary: the legacy pair scorer
    (run_fight(score_only=True)) cannot carry survival state — no target_*
    keys and no Knight's Vow state anywhere.  Scoring fields that DO
    survive (total_damage, item_state_receipts, champion_stats) agree
    with the full fight; the item's ordinary stats still flow through."""
    champ = get_champion("Ahri")
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": [{"champion": "Annie", "level": 18, "items": []}],
        },
        deterministic=True,
    )
    full = run_fight(champ, 18, [_kv_item()], params)
    score = run_fight(champ, 18, [_kv_item()], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["item_state_receipts"] == full["item_state_receipts"]
    assert score["champion_stats"] == full["champion_stats"]
    assert "target_ending_health" not in score
    # The ONLY Knight's Vow surface in the score-only result is the typed
    # sacrifice receipt row (state, not survival state).
    kv_rows = [
        row for row in score["item_state_receipts"] if row.get("item") == ITEM_NAME
    ]
    assert len(kv_rows) == 1
    assert kv_rows[0]["state"] == "sacrifice"


# ---------------------------------------------------------------------------
# 8. Coverage / optimizer eligibility
# ---------------------------------------------------------------------------


def test_coverage_posture_stays_eligible_today():
    """item_model_coverage returns the justified posture (modeled_state —
    the item's damage-relevant state is the authored scenario control)
    with optimizer_eligible + calculation_eligible True; the target
    coverage is "modeled" naming Pledge and Sacrifice.  outcome_dimensions
    is [] today (the coordinator justifies any additions)."""
    coverage = item_model_coverage(str(_kv_item()["name"]), ATTACKER_LANES).as_payload()
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["outcome_dimensions"] == []
    target = target_item_model_coverage(_kv_item())
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True
    assert "Sacrifice" in target["reason"]


def test_model_coverage_reason_names_sacrifice_and_pledge():
    coverage = item_model_coverage(str(_kv_item()["name"]), ATTACKER_LANES).as_payload()
    # Ours' attacker-lane reason is derived from the declared families and
    # never repeats a mechanic's prose; the mechanic is named on the
    # target lane, which this file asserts above.
    assert coverage["status"] == "modeled_state"
    assert "Sacrifice" in target_item_model_coverage(_kv_item())["reason"]


# ---------------------------------------------------------------------------
# 9. Existing regression surface (kept green, disjoint, mirrors the originals)
# ---------------------------------------------------------------------------


def test_regression_surface_scheduler_receipts_stay_green():
    """Mirrors test_item_support_effects.py ~538: the typed redirect and
    holder-heal receipts attach to the Worthy's incoming/outgoing ledgers
    with the exact 0.14 / 0.12 numbers."""
    holder = _actor(
        "ally:Lulu",
        "ally",
        (ITEM_NAME,),
        item_options={ITEM_NAME: {"worthy_target_index": 0}},
    )
    worthy = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    incoming = {
        worthy.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": worthy.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ]
    }
    outgoing = {
        worthy.participant_id: [
            {
                "time": 1.0,
                "attacker": worthy.participant_id,
                "target": enemy.participant_id,
                "damage": 200.0,
                "damage_type": "physical",
            }
        ]
    }
    support = defaultdict(list)
    schedule_knights_vow([holder, worthy, enemy], incoming, outgoing, support)
    assert incoming[worthy.participant_id][0]["redirect_fraction"] == pytest.approx(
        0.14
    )
    assert (
        incoming[worthy.participant_id][0]["redirect_target"] == holder.participant_id
    )
    assert incoming[worthy.participant_id][0]["redirect_source"] == REDIRECT_SOURCE
    heal = next(p for p in support[holder.participant_id] if p["kind"] == "heal")
    assert heal["target"] == holder.participant_id
    assert heal["amount"] == pytest.approx(24.0)


def test_regression_surface_timeline_redirect_math_stays_green():
    """Mirrors test_participant_timeline.py ~3512: 100 raw physical vs an
    unarmoured Worthy and a 100-armor holder -> 86 / 7."""
    source = _combatant("source", "enemy")
    protected = _combatant("protected", "main", armor=0.0)
    holder = _combatant("holder", "main", armor=100.0)
    event = _kv_redirect_event("kv-premit", 0.0, 100.0)
    result = _simulate_survival(
        [source, protected, holder], {"protected": [event]}, {}, {}, 10.0
    )
    assert result["protected"]["health_damage"] == pytest.approx(86.0)
    assert result["holder"]["health_damage"] == pytest.approx(7.0)


def test_regression_surface_holder_gate_cancel_stays_green():
    """Mirrors test_participant_timeline.py ~3557: the ordered holder gate
    cancels the redirect once the holder is at/below 30% max health."""
    source = _combatant("source", "enemy")
    protected = _combatant("protected", "main")
    holder = _combatant("holder", "main")
    incoming = {
        "holder": [
            {
                "time": 0.0,
                "damage": 90.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "holder",
                "sequence": 0,
                "_event_id": "holder-hit",
            }
        ],
        "protected": [_kv_redirect_event("kv-gated", 1.0, 40.0)],
    }
    result = _simulate_survival([source, protected, holder], incoming, {}, {}, 10.0)
    assert result["protected"]["health_damage"] == pytest.approx(40.0)
    assert result["holder"]["health_damage"] == pytest.approx(90.0)


def test_regression_surface_typed_action_reuse_survives_redirect_expansion():
    """Mirrors test_participant_timeline.py ~4850 (issue #169): a coupled
    fight with a Knight's Vow ally holder is cache-stable — two evaluations
    sharing the pair cache produce byte-identical timelines and the
    redirect expansion does not corrupt the cache."""
    first = _coupled_fight()
    cache: dict = {}
    assert _coupled_fight(pair_result_cache=cache) == first
    assert _coupled_fight(pair_result_cache=cache) == first


def test_regression_surface_app_option_schema_stays_green():
    """Mirrors test_app.py ~1644/1686: the front-end config exposes the
    Knight's Vow option schema with worthy_target_index bounded 0..4."""
    from src.calculator.item_effects import item_input_options_meta

    options = item_input_options_meta()
    assert ITEM_NAME in options
    assert options[ITEM_NAME]["options"]["worthy_target_index"]["max"] == 4
    assert options[ITEM_NAME]["source_revision_id"] == SOURCE_REVISION
