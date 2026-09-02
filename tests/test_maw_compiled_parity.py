"""P1 Package 3T — Maw of Malmortius (3156) "Lifeline" compiled-walk +
optimizer certification.

This file is the focused acceptance-matrix owner for Maw of Malmortius'
Lifeline.  It pins the OBSERVABLES the coordinator's P3-3T completion must
satisfy and runs against today's source: every behavior that already exists
passes now; every assertion that targets a contract piece the source does
not emit yet is marked ``xfail`` with reason ``awaiting P3-3T ...``.

Contract under test (current runtime facts, verified before pinning):

* ITEM IDENTITY: cached name "Maw of Malmortius", id 3156, price 3100
  (shop.prices.total, sell 1240), tier 3 LEGENDARY, builds from
  [3155 Hexdrinker, 3133 Caulfield's Warhammer].  Stats: +60 flat attack
  damage, +15 flat ability haste, +40 flat magic resistance (ordinary
  stat parity).  Passive "Lifeline" (unique); the cached riotDescription
  branch is exact: "Taking magic damage that would reduce your Health
  below 30% grants a magic damage Shield for 3 seconds and 10% Omnivamp
  until end of combat."  The cached passive branch carries the
  {{rd|200|150}} / {{rd|150%|112.5%}} melee-ranged markup.
* TYPED SOURCE: the ITEM_EFFECTS registry entry (type "stat_conversion")
  carries the nine Lifeline keys: health_threshold 0.30,
  shield_melee_base 200.0, shield_melee_bonus_ad_ratio 1.50,
  shield_ranged_base 150.0, shield_ranged_bonus_ad_ratio 1.125,
  duration 3.0, damage_type "magic", lifeline_omnivamp_percent 10.0.
  Every one of them is read through the registry's own fail-loud
  accessor, so a missing key raises naming "Maw of Malmortius" AND the
  key (CLAUDE.md rule 5 — no silent fallbacks).  The shield, health and
  duration keys are live ``ValueRef`` reads resolved on every build;
  damage_type is policy the catalog converts once when the rule is
  compiled, so only replacing the entry re-runs it.  A malformed value
  is a ValueRefError ("is not numeric") for strings and None alike.  The
  wiki source receipt rides the code-owned
  defensive_effects.defense_source(...) (revision 3984424, page rev timestamp
  2026-01-14T23:08:00Z) — the registry entry itself carries no source
  keys.
* TRIGGER + THRESHOLD: the shield is a magic-only Lifeline.  A magic
  packet whose would-be post-hit health is STRICTLY below 30% of the
  holder's maximum health at pool build arms the shield; damage landing
  exactly on the threshold does NOT arm ("damage that would reduce you
  below"); a holder already below 30% arms on the next magic packet.
  The armed shield absorbs the very hit that armed it.  PHYSICAL and
  TRUE damage never arm a magic-only shield, and the armed shield
  absorbs magic damage only.
* SHIELD AMOUNT: melee 200 + 150% bonus AD; ranged 150 + 112.5% bonus
  AD (the is_melee split).  There is NO level scaling — the {{rd|200|150}}
  markup is melee|ranged, NOT a level-scaled value: the amount is
  identical at level 1 and level 18 for equal bonus AD (contrast
  Hexdrinker's min/max level scaling).
* ONE-TRIGGER + DURATION: the Lifeline fires once per fight; the armed
  grant is timed and expires at trigger_time + 3.0s (the sourced
  duration); absorption only inside the window; no re-arm after the
  trigger (triggered flag + amount zeroed; the cached passive "cooldown"
  90 is a named boundary — the kernel authors no cooldown re-arm within
  a fight, and the calculator never re-fights, so the 90s cooldown is
  receipted but never enforced).
* OMNIVAMP WINDOW: maw_lifeline_omnivamp_percent 10.0 resolves onto the
  holder's defenses; on the triggering packet the ledger stamps
  maw_lifeline_omnivamp_activated: 10.0 and the holder's state flag
  maw_lifeline_omnivamp_active flips True and is NEVER cleared — the
  sourced "until end of combat" window.  Every subsequent non-reactive,
  non-deferred physical/magic packet the holder deals to another
  participant heals 10% of its post-mitigation damage (healing source
  "Maw of Malmortius (Lifeline omnivamp)", healing_category vamp); true
  damage and self-damage never heal.
* FAIL-CLOSED: Maw has no ITEM_INPUT_OPTIONS entry, so fabricated Maw
  item options are rejected ("Unknown item option target: Maw of
  Malmortius"); absent Maw -> zero threshold shield and zero omnivamp;
  a timed fight whose every damage event is NOT event-certified is
  withheld after computation (require_certified_target_timeline names
  the enemy item and the exact uncertified sources: "Result withheld:
  enemy item Maw of Malmortius needs a certified event timeline, but Q
  is not event-certified.").
* COMPILED VS RECEIPT PARITY: score path (include_receipt=False) and
  receipt walk agree on every observable (survival rows including the
  threshold fields, breakdown, duration, trigger timing, omnivamp
  receipts).  Today Maw sits in COMPILED_WALK_UNREPRESENTABLE_ITEMS
  ("Lifeline omnivamp state transition"), so the compiled fast path
  fails closed: a MAIN holder falls back per evaluation
  (context.uncompilable stays False, no panels built) and an
  ENEMY/ALLY holder poisons the search-invariant roster context
  (uncompilable True, panels empty) — both still deep-equal the receipt
  walk.  A tuple-ledger champion (Riven) holding Maw fails closed with
  parity and NO crash today (per-evaluation fallback, unpoisoned
  context).  The P3-3T certification (stage the threshold-lifeline and
  the omnivamp-until-combat-end state in the compiled kernel, remove
  the blocklist with byte-parity proof) is pinned as xfail: panels
  non-empty + uncompilable False + deep-equal for both the main holder
  and the roster holder.
* COVERAGE: item_model_coverage returns "modeled_effect" with
  optimizer_eligible + calculation_eligible True and outcome_dimensions
  [] today, but the reason is the GENERIC "Damage-relevant effects are
  represented by the fight model." — a Lifeline/magic-shield-naming
  reason (and a "defense" outcome dimension) is xfail (the coordinator's
  coverage tightening).  target_item_model_coverage is
  "modeled_event_certified" naming the bonus-AD-scaled 30%-health magic
  shield and the certified-timeline gate.
* ITEM STATE RECEIPTS: the 3M/3N/3O-pattern item_state_receipts row for
  Lifeline (state "lifeline" per the coordinator's pin, the typed
  values, source_url + source_revision_id 3984424, and the named
  boundaries) is absent today — xfail.
* XFAIL ONLY for genuinely absent mechanics: (1) the compiled-panel
  certification for the main holder; (2) the roster-holder compilation;
  (3) the coverage reason naming Lifeline/magic shield (plus the
  "defense" outcome dimension); (4) the item_state_receipts Maw row.
  All four are ``awaiting P3-3T ...``.

Coordinator ambiguities surfaced by this matrix (see the reply):

* The melee/ranged markup {{rd|200|150}} is melee|ranged, NOT
  level-scaled: pinned by the typed keys and by identical level-1 and
  level-18 amounts.  There is no level term for Maw anywhere.
* The omnivamp window is a never-cleared state flag: "until end of
  combat" == from the triggering packet through fight end (every
  subsequent qualifying outgoing packet heals 10%).  There is no
  cooldown reset inside a fight; the cached passive "cooldown": "90" is
  a named boundary, never enforced.
* The event-certified gate is require_certified_target_timeline in
  calculate.py: a NON-one-rotation timed fight whose
  timeline_coverage["complete"] is False with an enemy Maw holder is
  withheld with a ValueError naming the enemy item and the coarse
  sources.  one_rotation fights skip the gate.
* All six typed keys now name the item as well as the key: the reads go
  through ``required_effect_value`` / ``ValueRef``, so the item-naming
  claim holds for the whole set and the bare-KeyError gap is closed.
* The receipt row state name is pinned "lifeline" provisionally — the
  coordinator's 3M/3N/3O pattern decides the exact state string (the
  row itself is absent today).

Sibling owners: the compiled-vs-receipt kernel contract lives in
``tests/test_survival_kernel.py`` (issue #137); the 3Q/3S matrix shapes
in ``tests/test_force_of_nature_compiled_parity.py`` and
``tests/test_knights_vow_compiled_parity.py``; the Lifeline family
regression surface in ``tests/test_issues_46.py`` (threshold trigger +
omnivamp toggle + BIS), ``tests/test_shield_ledger.py`` (magic-only
absorption + strict threshold), ``tests/test_defensive_effects.py``
(melee/ranged amounts), ``tests/test_participant_timeline.py``
(post-trigger omnivamp heal), ``tests/test_issue_159.py`` (strict
threshold in both walks), and ``tests/test_item_coverage.py``
(modeled_event_certified + certified-timeline guard).  This file is
disjoint and pins only the Maw acceptance observables.
"""

import pytest

from src import app as app_module
from src.calculator.data_fetcher import get_champion, get_item_by_name

# The retired per-item ``_X_SOURCE`` constant, read from the one home it
# moved to: the declaration's own resolved citation.
from src.calculator.defensive_effects import (
    StartingDefenses,
    defense_source,
    resolve_starting_defenses,
)
from src.calculator.item_behavior import DefenseMechanic
from src.calculator.item_coverage import (
    ATTACKER_LANES,
    item_model_coverage,
    require_certified_target_timeline,
    target_item_model_coverage,
)
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    item_state_receipts,
    required_effect_value,
    validate_item_input_options,
)
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.state_lifecycle import SourceReceipt
from src.calculator.stats import calculate_total_stats

# Ours' declaration layer raises its own fail-closed error where main's
# accessor raised KeyError; both refuse the corrupted value.
from src.calculator.value_ref import ValueRefError
from tests.app_config import app_config
from tests.survival_probe import simulate_survival

_SOURCE = defense_source("Maw of Malmortius", DefenseMechanic.LIFELINE_MAW)

ITEM_NAME = "Maw of Malmortius"
ITEM_ID = 3156
PRICE = 3100
SELL = 1240
AD_FLAT = 60.0
AH_FLAT = 15.0
MR_FLAT = 40.0
HEALTH_THRESHOLD = 0.30
SHIELD_MELEE_BASE = 200.0
SHIELD_MELEE_AD_RATIO = 1.50
SHIELD_RANGED_BASE = 150.0
SHIELD_RANGED_AD_RATIO = 1.125
SHIELD_DURATION = 3.0
DAMAGE_TYPE = "magic"
OMNIVAMP_PERCENT = 10.0
SOURCE_REVISION = 3984424
# The cached riotDescription branch — the exact Lifeline sentence.
BRANCH_FRAGMENTS = (
    "<passive>Lifeline</passive>",
    "reduce your Health below 30%",
    "magic damage Shield",
    "for 3 seconds",
    "10% Omnivamp",
    "until end of combat",
)
# The cached passive branch markup that resolves the melee/ranged reading:
# {{rd|200|150}} is melee 200 / ranged 150 (NOT a level-scaled value) and
# {{rd|150%|112.5%}} is melee 150% / ranged 112.5% bonus AD.
BRANCH_MARKUP_FRAGMENTS = ("{{rd|200|150}}", "{{rd|150%|{{fd|112.5}}%}}")
# Ahri level 18 is ranged; with the item's 60 bonus AD the sourced shield
# is 150 + 1.125 x 60 = 217.5 (pinned in the coupled fight below).
AHRi_SHIELD = SHIELD_RANGED_BASE + SHIELD_RANGED_AD_RATIO * AD_FLAT


@pytest.fixture(autouse=True)
def _disable_rate_limits():
    with app_config(RATE_LIMIT_ENABLED=False):
        yield


def _maw_item() -> dict:
    """The real cached item record (id 3156)."""
    return get_item_by_name(ITEM_NAME)


def _stats(**overrides) -> dict:
    stats = {
        "health": 3000.0,
        "is_melee": True,
        "bonus_attack_damage": 0.0,
    }
    stats.update(overrides)
    return stats


def _holder(
    health: float,
    *,
    is_melee: bool = True,
    bonus_attack_damage: float = 0.0,
    items: tuple[dict, ...] | None = None,
) -> Combatant:
    """A Maw holder used by the packet-level survival-walk probes."""
    stats = _stats(
        health=health, is_melee=is_melee, bonus_attack_damage=bonus_attack_damage
    )
    item_list = ({"name": ITEM_NAME},) if items is None else items
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Aatrox"},
        level=18,
        items=(_maw_item(),) if items is None else items,
        stats=stats,
        defenses=resolve_starting_defenses("Aatrox", 18, stats, list(item_list)),
    )


def _dummy_source(participant_id: str = "source", team: str = "enemy") -> Combatant:
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": 5000.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )


def _packet(
    time: float,
    sequence: int,
    *,
    damage: float,
    damage_type: str,
    attacker: str = "source",
    source_key: str = "Q",
    **extra,
) -> dict:
    packet = {
        "time": time,
        "damage": damage,
        "damage_type": damage_type,
        "attacker": attacker,
        "target": "target",
        "source_key": source_key,
        "sequence": sequence,
        "_event_id": f"{source_key}:{sequence}:{time}",
    }
    packet.update(extra)
    return packet


def _run_packets(
    holder: Combatant,
    events: list[dict],
    *,
    duration: float = 10.0,
    holder_id: str = "target",
) -> dict:
    """Run one _simulate_survival with the Maw holder as target."""
    return simulate_survival(
        [_dummy_source(), holder], {holder_id: events}, {}, {}, duration
    )


def _row(result: dict, participant_id: str = "target") -> dict:
    return result[participant_id]


def _holder_fight(
    duration: float,
    *,
    include_receipt: bool = True,
    search_context: CoupledSearchContext | None = None,
    arm_lifeline: bool = True,
) -> dict:
    """A coupled fight where the MAIN (Ahri, ranged) holds Maw against a
    magic dealer (Cassiopeia).

    The 16-second Cassiopeia fixture crosses the 30% threshold at t=9.5,
    absorbs the full 217.5 ranged shield, stamps the omnivamp activation,
    and authors post-trigger vamp heals — the whole Lifeline machine.
    ``include_receipt=False`` returns the coupled score surface; passing a
    ``search_context`` plus an empty pair cache exercises the compiled
    score path (which must fail closed on Maw today and fall back to the
    shared walk).  ``arm_lifeline=False`` keeps the item data (so the pair
    fight still sees the +60 AD / +15 AH / +40 MR stats) while leaving
    Lifeline unarmed — the byte-identical control for the ordinary-stat
    parity pin.
    """
    main = get_champion("Ahri")
    items = [_maw_item()] if arm_lifeline else []
    main_stats = calculate_total_stats(main, 18, items)
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
    enemy_loadout = ChampionLoadout(champion="Cassiopeia", level=18, items=[]).resolve()
    defenses = resolve_starting_defenses("Ahri", 18, main_stats, items)
    return build_participant_timeline(
        main,
        18,
        items,
        params,
        main_stats=main_stats,
        main_defenses=defenses,
        enemies=[enemy_loadout],
        allies=[],
        include_receipt=include_receipt,
        pair_result_cache={} if search_context is not None else None,
        search_context=search_context,
    )


def _main_survival(result: dict) -> dict:
    """The main holder's survival row (participant 0)."""
    return result["participants"][0]["survival"]


# ---------------------------------------------------------------------------
# 1. Identity / stats / passive
# ---------------------------------------------------------------------------


def test_cached_identity_pins_name_id_price_stats_and_lifeline_branch():
    item = _maw_item()
    assert item["name"] == ITEM_NAME
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["shop"]["prices"]["sell"] == SELL
    assert item["tier"] == 3
    assert item["rank"] == ["LEGENDARY"]
    assert item["buildsFrom"] == [3155, 3133]
    assert item["stats"]["attackDamage"]["flat"] == AD_FLAT
    assert item["stats"]["abilityHaste"]["flat"] == AH_FLAT
    assert item["stats"]["magicResistance"]["flat"] == MR_FLAT
    (passive,) = item["passives"]
    assert passive["name"] == "Lifeline"
    assert passive["unique"] is True
    branch = item["riotDescription"]
    for fragment in BRANCH_FRAGMENTS:
        assert fragment in branch
    # The melee/ranged markup lives on the cached passive branch.
    cached_branch = " ".join(passive.get("branches", ()))
    for fragment in BRANCH_MARKUP_FRAGMENTS:
        assert fragment in cached_branch


def test_equipping_maw_yields_exactly_60_ad_15_ah_and_40_mr():
    main = get_champion("Ahri")
    base = calculate_total_stats(main, 18, [])
    with_maw = calculate_total_stats(main, 18, [_maw_item()])
    diffs = {key: with_maw[key] - base[key] for key in with_maw}
    changed = {key: round(value, 4) for key, value in diffs.items() if value != 0.0}
    assert changed == {
        "attack_damage": AD_FLAT,
        "bonus_attack_damage": AD_FLAT,
        "ability_haste": AH_FLAT,
        "magic_resistance": MR_FLAT,
        "bonus_magic_resistance": MR_FLAT,
    }


def test_arm_lifeline_false_control_keeps_the_ordinary_stats():
    """The fail-closed control: with the item equipped but Lifeline unarmed
    the stats still flow (+60 AD on Ahri's auto/ability math) while the
    survival row shows no threshold trigger."""
    armed = _holder_fight(16.0)
    unarmed = _holder_fight(16.0, arm_lifeline=False)
    assert unarmed["participants"][0]["survival"]["threshold_shield_triggered"] is False
    assert unarmed["participants"][0]["survival"]["threshold_shield_expired_at"] is None
    # The stats parity is pinned above; here only that the fight runs and
    # the two surfaces agree byte-for-byte with the same unarmed build.
    assert armed["duration"] == unarmed["duration"]


# ---------------------------------------------------------------------------
# 2. Typed source values
# ---------------------------------------------------------------------------


def test_typed_lifeline_values_return_exact_numbers():
    effect = ITEM_EFFECTS[ITEM_NAME]
    assert effect["type"] == "stat_conversion"
    assert float(effect["health_threshold"]) == pytest.approx(HEALTH_THRESHOLD)
    assert float(effect["shield_melee_base"]) == pytest.approx(SHIELD_MELEE_BASE)
    assert float(effect["shield_melee_bonus_ad_ratio"]) == pytest.approx(
        SHIELD_MELEE_AD_RATIO
    )
    assert float(effect["shield_ranged_base"]) == pytest.approx(SHIELD_RANGED_BASE)
    assert float(effect["shield_ranged_bonus_ad_ratio"]) == pytest.approx(
        SHIELD_RANGED_AD_RATIO
    )
    assert float(effect["duration"]) == pytest.approx(SHIELD_DURATION)
    assert str(effect["damage_type"]) == DAMAGE_TYPE
    assert float(effect["lifeline_omnivamp_percent"]) == pytest.approx(OMNIVAMP_PERCENT)
    # The typed reads the engine actually consumes.
    assert str(required_effect_value(ITEM_NAME, "damage_type")) == DAMAGE_TYPE
    assert float(
        required_effect_value(ITEM_NAME, "lifeline_omnivamp_percent")
    ) == pytest.approx(OMNIVAMP_PERCENT)


def test_lifeline_source_rides_the_reviewed_source_receipt():
    """The wiki source receipt rides defensive_effects.defense_source(...)
    (code-owned, revision 3984424); the ITEM_EFFECTS registry entry itself
    carries no source keys, so the source pin is the code-owned receipt."""
    assert not ({"source_url", "source_revision_id"} & set(ITEM_EFFECTS[ITEM_NAME]))
    assert ITEM_NAME not in ITEM_INPUT_OPTIONS
    assert _SOURCE.label == "Maw of Malmortius — Lifeline"
    assert (
        _SOURCE.source_url == "https://wiki.leagueoflegends.com/en-us/Maw_of_Malmortius"
    )
    assert _SOURCE.revision_id == SOURCE_REVISION
    assert _SOURCE.revision_timestamp == "2026-01-14T23:08:00Z"
    source = SourceReceipt(
        label=_SOURCE.label,
        url=_SOURCE.source_url,
        revision_id=_SOURCE.revision_id,
        revision_timestamp=_SOURCE.revision_timestamp,
    )
    assert source.revision_id == SOURCE_REVISION


def test_starting_defenses_resolve_the_lifeline_fields():
    defenses = resolve_starting_defenses("Aatrox", 18, _stats(), [{"name": ITEM_NAME}])
    assert defenses.threshold_shield_amount == pytest.approx(SHIELD_MELEE_BASE)
    assert defenses.threshold_shield_health_ratio == pytest.approx(HEALTH_THRESHOLD)
    assert defenses.threshold_shield_duration == pytest.approx(SHIELD_DURATION)
    assert defenses.threshold_shield_damage_type == DAMAGE_TYPE
    assert defenses.maw_lifeline_omnivamp_percent == pytest.approx(OMNIVAMP_PERCENT)
    summary = defenses.public_summary()
    assert summary["threshold_shield"] == {
        "amount": SHIELD_MELEE_BASE,
        "health_ratio": HEALTH_THRESHOLD,
        "duration": SHIELD_DURATION,
        "damage_type": DAMAGE_TYPE,
    }
    assert summary["maw_lifeline_omnivamp_percent"] == pytest.approx(OMNIVAMP_PERCENT)
    assert any("Maw of Malmortius" in text for text in defenses.assumptions)
    assert any(
        "omnivamp only after Lifeline triggers" in text for text in defenses.assumptions
    )


_DELETE = object()


def _corrupt_in_place(monkeypatch, key, value=_DELETE):
    """Edit the LIVE entry, so a live reference resolves the damage.

    A ``ValueRef`` holds the registry and the key, not the value, so it
    reads whatever the entry says at resolve time.  Rebinding the *name*
    would leave the reference pointing at the intact mapping, which is why
    the corruption goes into the entry object itself.
    """
    if value is _DELETE:
        monkeypatch.delitem(ITEM_EFFECTS[ITEM_NAME], key)
    else:
        monkeypatch.setitem(ITEM_EFFECTS[ITEM_NAME], key, value)


def _corrupt_by_replacement(monkeypatch, key, value=_DELETE):
    """Replace the whole entry, so the rule memo recompiles from it.

    ``behavior_rules`` re-checks its memo by entry *object identity*, so a
    key the rule resolves once at compile time — a policy enum like
    ``damage_type`` — is only re-read when the entry object is replaced.
    """
    corrupted = dict(ITEM_EFFECTS[ITEM_NAME])
    if value is _DELETE:
        del corrupted[key]
    else:
        corrupted[key] = value
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, corrupted)


def test_missing_typed_key_fails_loud_naming_item_and_key():
    """The two ``required_effect_value`` reads name the item AND the key.

    They fail at different moments and so are corrupted differently:
    ``lifeline_omnivamp_percent`` is a live reference the resolver reads on
    every build, while ``damage_type`` is policy the catalog converts once
    when the rule is compiled — so only replacing the entry re-runs it.
    """
    for corrupt, missing in (
        (_corrupt_by_replacement, "damage_type"),
        (_corrupt_in_place, "lifeline_omnivamp_percent"),
    ):
        with pytest.MonkeyPatch.context() as patch:
            corrupt(patch, missing)
            with pytest.raises((KeyError, ValueRefError)) as excinfo:
                resolve_starting_defenses("Aatrox", 18, _stats(), [{"name": ITEM_NAME}])
            message = str(excinfo.value)
            assert ITEM_NAME in message
            assert missing in message


def test_missing_shield_keys_still_fail_closed_with_a_key_error():
    """Every companion key is a live reference: deleting one is a stop.

    Each key is corrupted in its own ``monkeypatch`` context, because a
    corruption that outlived its case would let the *first* missing key
    answer for the second and the assertion would pass on the wrong stop.
    """
    for missing in (
        "shield_melee_base",
        "shield_melee_bonus_ad_ratio",
        "health_threshold",
        "duration",
    ):
        with pytest.MonkeyPatch.context() as patch:
            _corrupt_in_place(patch, missing)
            with pytest.raises((KeyError, ValueRefError)) as excinfo:
                resolve_starting_defenses("Aatrox", 18, _stats(), [{"name": ITEM_NAME}])
            assert ITEM_NAME in str(excinfo.value)
            assert missing in str(excinfo.value)


def test_malformed_typed_values_fail_loudly():
    """A non-numeric value is a ``ValueRefError`` naming the item and key."""
    for key, value in (
        ("shield_melee_base", "two hundred"),
        ("duration", None),
        ("lifeline_omnivamp_percent", "ten"),
    ):
        with pytest.MonkeyPatch.context() as patch:
            _corrupt_in_place(patch, key, value)
            with pytest.raises(ValueRefError) as excinfo:
                resolve_starting_defenses("Aatrox", 18, _stats(), [{"name": ITEM_NAME}])
            assert ITEM_NAME in str(excinfo.value)
            assert key in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Magic-damage trigger + below-30% threshold
# ---------------------------------------------------------------------------


def test_magic_hit_crossing_below_thirty_percent_arms_and_blocks_itself():
    """1000 health, threshold 300: an 800 magic hit would leave 200 (< 300),
    so the 200 base melee shield arms and blocks the very hit that armed
    it: 200 absorbed, 600 applied, ending 400."""
    holder = _holder(1000.0)
    result = _run_packets(holder, [_packet(0.0, 0, damage=800.0, damage_type="magic")])
    row = _row(result)
    assert row["threshold_shield_triggered"] is True
    assert row["threshold_shield_expired_at"] == pytest.approx(SHIELD_DURATION)
    assert row["shield_absorbed"] == pytest.approx(SHIELD_MELEE_BASE)
    assert row["ending_health"] == pytest.approx(400.0)


def test_damage_landing_exactly_on_the_threshold_does_not_arm():
    """Sourced as damage that would reduce you *below* 30%: 1000 health,
    700 magic lands exactly on 300 — no arm."""
    holder = _holder(1000.0)
    result = _run_packets(holder, [_packet(0.0, 0, damage=700.0, damage_type="magic")])
    row = _row(result)
    assert row["threshold_shield_triggered"] is False
    assert row["ending_health"] == pytest.approx(300.0)
    assert row["shield_absorbed"] == pytest.approx(0.0)


def test_damage_one_unit_past_the_threshold_arms():
    holder = _holder(1000.0)
    result = _run_packets(holder, [_packet(0.0, 0, damage=701.0, damage_type="magic")])
    row = _row(result)
    assert row["threshold_shield_triggered"] is True
    assert row["ending_health"] == pytest.approx(1000.0 - (701.0 - 200.0))


def test_a_holder_already_below_thirty_percent_arms_on_the_next_magic_hit():
    """The threshold check is on the would-be post-hit health (30% of the
    pool-build maximum): physical damage can carry the holder below the
    line without arming (magic-only), and the next magic packet then arms
    because the would-be post-hit health stays strictly below the
    threshold."""
    holder = _holder(1000.0)
    events = [
        _packet(0.0, 0, damage=800.0, damage_type="physical"),  # 200 < 300, no arm
        _packet(1.0, 1, damage=10.0, damage_type="magic"),  # 190 < 300, arms
    ]
    result = _run_packets(holder, events)
    row = _row(result)
    assert row["threshold_shield_triggered"] is True
    # The armed shield blocks the very hit that armed it: the 10 magic is
    # absorbed and health stays at 200 (the physical crossing already
    # applied).
    assert row["shield_absorbed"] == pytest.approx(10.0)
    assert row["ending_health"] == pytest.approx(200.0)


def test_physical_damage_never_arms_a_magic_only_lifeline():
    holder = _holder(1000.0)
    result = _run_packets(
        holder, [_packet(0.0, 0, damage=800.0, damage_type="physical")]
    )
    row = _row(result)
    assert row["threshold_shield_triggered"] is False
    assert row["ending_health"] == pytest.approx(200.0)
    assert row["shield_absorbed"] == pytest.approx(0.0)


def test_true_damage_never_arms_a_magic_only_lifeline():
    holder = _holder(1000.0)
    result = _run_packets(holder, [_packet(0.0, 0, damage=800.0, damage_type="true")])
    row = _row(result)
    assert row["threshold_shield_triggered"] is False
    assert row["ending_health"] == pytest.approx(200.0)
    assert row["shield_absorbed"] == pytest.approx(0.0)


def test_a_physical_hit_after_arming_passes_through_the_magic_shield():
    """The armed magic shield absorbs magic damage only: a physical hit
    inside the window is not absorbed (mirrors test_shield_ledger)."""
    holder = _holder(1000.0, bonus_attack_damage=400.0)  # shield 200 + 600 = 800
    events = [
        _packet(0.0, 0, damage=750.0, damage_type="magic"),  # arms, absorbs 750
        _packet(1.0, 1, damage=100.0, damage_type="physical"),  # passes through
    ]
    result = _run_packets(holder, events)
    row = _row(result)
    assert row["threshold_shield_triggered"] is True
    assert row["shield_absorbed"] == pytest.approx(750.0)
    assert row["ending_health"] == pytest.approx(1000.0 - 100.0)


# ---------------------------------------------------------------------------
# 4. Shield amount (melee/ranged split; no level scaling) + duration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("is_melee", "bonus_ad", "expected"),
    [
        (True, 0.0, 200.0),
        (True, 60.0, 290.0),
        (True, 100.0, 350.0),
        (False, 0.0, 150.0),
        (False, 60.0, 217.5),
        (False, 100.0, 262.5),
    ],
)
def test_shield_amount_is_base_plus_bonus_ad_ratio_by_range_type(
    is_melee, bonus_ad, expected
):
    defenses = resolve_starting_defenses(
        "Aatrox" if is_melee else "Caitlyn",
        18,
        _stats(is_melee=is_melee, bonus_attack_damage=bonus_ad),
        [{"name": ITEM_NAME}],
    )
    assert defenses.threshold_shield_amount == pytest.approx(expected)
    assert defenses.threshold_shield_damage_type == DAMAGE_TYPE
    assert defenses.threshold_shield_duration == pytest.approx(SHIELD_DURATION)


def test_shield_amount_has_no_level_scaling():
    """The {{rd|200|150}} markup is melee|ranged, NOT a level-scaled value:
    identical amounts at level 1 and level 18 for equal bonus AD (contrast
    Hexdrinker's min/max level scaling)."""
    melee_1 = resolve_starting_defenses(
        "Aatrox",
        1,
        _stats(is_melee=True, bonus_attack_damage=100.0),
        [{"name": ITEM_NAME}],
    )
    melee_18 = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(is_melee=True, bonus_attack_damage=100.0),
        [{"name": ITEM_NAME}],
    )
    ranged_1 = resolve_starting_defenses(
        "Caitlyn",
        1,
        _stats(is_melee=False, bonus_attack_damage=100.0),
        [{"name": ITEM_NAME}],
    )
    ranged_18 = resolve_starting_defenses(
        "Caitlyn",
        18,
        _stats(is_melee=False, bonus_attack_damage=100.0),
        [{"name": ITEM_NAME}],
    )
    assert melee_1.threshold_shield_amount == pytest.approx(350.0)
    assert melee_18.threshold_shield_amount == pytest.approx(350.0)
    assert ranged_1.threshold_shield_amount == pytest.approx(262.5)
    assert ranged_18.threshold_shield_amount == pytest.approx(262.5)


def test_armed_shield_expires_after_the_sourced_three_seconds():
    """Trigger at t=0 (shield 800 with 400 bonus AD): the arming hit absorbs
    750, an in-window magic hit absorbs the remaining 50, and a magic hit at
    t=4 (past trigger + 3.0) is NOT absorbed."""
    holder = _holder(1000.0, bonus_attack_damage=400.0)
    events = [
        _packet(0.0, 0, damage=750.0, damage_type="magic"),
        _packet(1.0, 1, damage=40.0, damage_type="magic"),
        _packet(4.0, 2, damage=40.0, damage_type="magic"),
    ]
    result = _run_packets(holder, events)
    row = _row(result)
    assert row["threshold_shield_triggered"] is True
    assert row["threshold_shield_expired_at"] == pytest.approx(SHIELD_DURATION)
    assert row["shield_absorbed"] == pytest.approx(750.0 + 40.0)
    assert row["ending_health"] == pytest.approx(1000.0 - 40.0)


# ---------------------------------------------------------------------------
# 5. One-trigger + omnivamp window
# ---------------------------------------------------------------------------


def test_lifeline_fires_once_per_fight_with_no_retrigger():
    """After the first arm the triggered flag is set and the amount zeroed:
    further magic crossing hits never re-arm (mirrors test_shield_ledger's
    arms-only-once)."""
    holder = _holder(1000.0)
    events = [
        _packet(0.0, 0, damage=800.0, damage_type="magic"),
        _packet(1.0, 1, damage=500.0, damage_type="magic"),
        _packet(2.0, 2, damage=500.0, damage_type="magic"),
    ]
    result = _run_packets(holder, events)
    row = _row(result)
    assert row["threshold_shield_triggered"] is True
    # Only the first grant ever absorbs.
    assert row["shield_absorbed"] == pytest.approx(SHIELD_MELEE_BASE)
    assert row["ending_health"] == pytest.approx(0.0)
    assert row["health_damage"] == pytest.approx(1000.0)


def test_post_trigger_omnivamp_heals_ten_percent_until_end_of_combat():
    """The sourced window is "until end of combat": the state flag flips at
    the trigger and is never cleared, so every subsequent qualifying
    outgoing packet heals 10% of post-mitigation damage (physical AND
    magic); true damage never heals; nothing heals before the trigger."""
    holder = _holder(1000.0)
    incoming = {
        "target": [_packet(0.0, 0, damage=800.0, damage_type="magic")],
        "source": [
            _packet(
                1.0,
                0,
                damage=100.0,
                damage_type="physical",
                attacker="target",
                target="source",
                basic_attack=True,
                source_key="auto_attacks",
            ),
            _packet(
                2.0,
                1,
                damage=50.0,
                damage_type="true",
                attacker="target",
                target="source",
                source_key="R",
            ),
            _packet(
                3.0,
                2,
                damage=200.0,
                damage_type="magic",
                attacker="target",
                target="source",
                source_key="Q",
            ),
        ],
    }
    result = simulate_survival([holder, _dummy_source()], incoming, {}, {}, 5.0)
    row = _row(result)
    assert row["threshold_shield_triggered"] is True
    # 10% of 100 physical + 10% of 200 magic = 30; the true hit heals 0.
    assert row["healing_received"] == pytest.approx(30.0)


def test_no_omnivamp_heal_before_the_lifeline_triggers():
    holder = _holder(1000.0)
    incoming = {
        "target": [_packet(2.0, 0, damage=50.0, damage_type="magic")],
        "source": [
            _packet(
                1.0,
                0,
                damage=100.0,
                damage_type="physical",
                attacker="target",
                target="source",
                basic_attack=True,
                source_key="auto_attacks",
            ),
        ],
    }
    result = simulate_survival([holder, _dummy_source()], incoming, {}, {}, 5.0)
    assert _row(result)["threshold_shield_triggered"] is False
    assert _row(result)["healing_received"] == pytest.approx(0.0)


def test_omnivamp_field_is_zero_when_maw_is_absent():
    defenses = resolve_starting_defenses("Aatrox", 18, _stats(), [])
    assert defenses.maw_lifeline_omnivamp_percent == 0.0
    assert defenses.threshold_shield_amount == 0.0


# ---------------------------------------------------------------------------
# 6. Fail-closed
# ---------------------------------------------------------------------------


def test_fabricated_maw_item_options_are_rejected_fail_closed():
    """Maw exposes no scenario control (no ITEM_INPUT_OPTIONS entry at all),
    so ANY fabricated option target under it is rejected with the unknown-
    target error naming the item."""
    assert ITEM_NAME not in ITEM_INPUT_OPTIONS
    with pytest.raises(ValueError) as excinfo:
        validate_item_input_options({ITEM_NAME: {"lifeline_omnivamp_percent": 10}})
    assert "Unknown item option target" in str(excinfo.value)
    assert ITEM_NAME in str(excinfo.value)


def test_certified_timeline_guard_withholds_uncertified_maw_fights():
    """The event-certified gate: a timed fight whose timeline is not
    complete is withheld when the enemy holds Maw, naming the item AND the
    exact uncertified source."""
    with pytest.raises(
        ValueError,
        match=r"Maw of Malmortius.*muramana_ability is not event-certified",
    ):
        require_certified_target_timeline(
            [_maw_item()],
            {"complete": False, "coarse_sources": ["muramana_ability"]},
        )


def test_certified_timeline_guard_allows_certified_maw_fights():
    require_certified_target_timeline(
        [_maw_item()], {"complete": True, "coarse_sources": []}
    )


def test_certified_timeline_guard_ignores_targets_without_maw():
    require_certified_target_timeline(
        [get_item_by_name("Kaenic Rookern")],
        {"complete": False, "coarse_sources": ["passive"]},
    )


def _maw_timed_request() -> dict:
    """A timed Shen fight against a Galio holding Maw."""
    return {
        "champion": "Shen",
        "level": 18,
        "items": [],
        "fight_mode": "timed",
        "fight_duration": 8,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.8,
        "enemies": [
            {"champion": "Galio", "level": 18, "items": [ITEM_NAME], "role": "top"}
        ],
    }


def test_calculate_api_certifies_the_timed_maw_fight_it_once_withheld():
    """The frontier closed: Shen's Q is event-ordered, so the fight computes.

    Every registered attacker reaches ``event_order_certified`` on a plain
    timed fight, so this case has no uncertified subject to withhold — the
    *premise* retired rather than the gate, which is why the fight is
    pinned as certified here and the withholding is driven below.
    """
    client = app_module.app.test_client()
    response = client.post("/api/calculate", json=_maw_timed_request())

    assert response.status_code == 200, response.get_json()
    coverage = response.get_json()["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["certification"] == "event_order_certified"
    assert coverage["coarse_sources"] == []


def test_calculate_api_withholds_an_uncertified_timed_fight_with_maw_enemy(
    monkeypatch,
):
    """API-level pin that the gate is *on the route*, not just importable.

    The coverage a fight reports is what the gate reads, so an incomplete
    one is fed in at the seam ``/api/calculate`` hands to
    ``require_certified_target_timeline``.  Driving it this way keeps the
    route's claim independent of which champions happen to be certified.
    """
    from src.calculator import calculate as calculate_module

    real_run_fight = calculate_module.run_fight

    def uncertified(*args, **kwargs):
        result = real_run_fight(*args, **kwargs)
        result["timeline_coverage"] = {
            "complete": False,
            "certification": "coarse",
            "exact_sources": [],
            "coarse_sources": ["Q"],
            "note": "planted",
        }
        return result

    monkeypatch.setattr(calculate_module, "run_fight", uncertified)
    client = app_module.app.test_client()
    response = client.post("/api/calculate", json=_maw_timed_request())

    assert response.status_code == 400
    body = response.get_json()
    assert "Result withheld" in body["error"]
    assert "enemy item Maw of Malmortius" in body["error"]
    assert "Q is not event-certified" in body["error"]

    without_maw = _maw_timed_request()
    without_maw["enemies"] = [
        {"champion": "Galio", "level": 18, "items": [], "role": "top"}
    ]
    assert client.post("/api/calculate", json=without_maw).status_code == 200


def test_calculate_api_models_the_enemy_maw_shield_in_certified_timed_fights():
    """Certified timed fight: the enemy holder's Lifeline arms, the target
    result reports the threshold absorption, and the enemy's post-trigger
    outgoing damage heals from the temporary omnivamp (mirrors
    test_issues_46)."""
    client = app_module.app.test_client()
    payload = {
        "champion": "Ziggs",
        "level": 18,
        "items": ["Rabadon's Deathcap", "Shadowflame", "Liandry's Torment"],
        "fight_mode": "timed",
        "fight_duration": 10,
        "enemies": [
            {"champion": "Galio", "level": 18, "items": [ITEM_NAME], "role": "top"}
        ],
    }
    response = client.post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    target = body["targets"][0]
    starting = target["target"]["starting_defenses"]
    assert starting["threshold_shield"]["amount"] == pytest.approx(290.0)
    assert starting["threshold_shield"]["damage_type"] == "magic"
    assert starting["maw_lifeline_omnivamp_percent"] == pytest.approx(10.0)
    assert target["result"]["threshold_shield_absorbed"] == pytest.approx(290.0)
    galio = next(
        row for row in body["combat"]["participants"] if row["champion"] == "Galio"
    )
    assert galio["survival"]["threshold_shield_triggered"] is True
    assert galio["survival"]["healing_received"] > 0.0
    triggered = [
        event
        for event in body["combat"]["events"]
        if event.get("threshold_shield_triggered")
    ]
    assert triggered
    assert triggered[0]["maw_lifeline_omnivamp_activated"] == pytest.approx(10.0)
    assert galio["survival"]["threshold_shield_expired_at"] == pytest.approx(
        triggered[0]["time"] + SHIELD_DURATION
    )
    maw_heals = [
        event
        for event in body["combat"].get("healing_events", [])
        if "Maw of Malmortius" in str(event.get("source", ""))
    ]
    assert maw_heals
    assert all(event["time"] >= triggered[0]["time"] for event in maw_heals)


# ---------------------------------------------------------------------------
# 7. Receipt fields + source evidence
# ---------------------------------------------------------------------------


def test_item_state_receipts_emits_no_maw_row_today():
    """P3-3T: item_state_receipts emits exactly ONE lifeline row carrying
    the typed Lifeline declaration and the source receipt."""
    receipts = item_state_receipts(
        [_maw_item()], {}, fight_duration_seconds=16.0, is_melee=False
    )
    (row,) = [r for r in receipts if r.get("item") == ITEM_NAME]
    assert row["state"] == "lifeline"
    assert row["health_threshold"] == pytest.approx(HEALTH_THRESHOLD)
    assert row["shield_melee_base"] == pytest.approx(SHIELD_MELEE_BASE)
    assert row["shield_melee_bonus_ad_ratio"] == pytest.approx(SHIELD_MELEE_AD_RATIO)
    assert row["shield_ranged_base"] == pytest.approx(SHIELD_RANGED_BASE)
    assert row["shield_ranged_bonus_ad_ratio"] == pytest.approx(SHIELD_RANGED_AD_RATIO)
    assert row["duration_seconds"] == pytest.approx(SHIELD_DURATION)
    assert row["damage_type"] == "magic"
    assert row["lifeline_omnivamp_percent"] == pytest.approx(OMNIVAMP_PERCENT)
    assert row["source_revision_id"] == SOURCE_REVISION


def test_item_state_receipts_emits_exactly_one_lifeline_row():
    """P3-3T contract (receipt path, the 3M/3N/3O pattern):
    item_state_receipts emits exactly ONE Maw row — state "lifeline" —
    carrying the nine typed values, the wiki source receipt, and the named
    boundaries (the cached 90s passive cooldown is not enforced inside a
    fight; the omnivamp window runs from the trigger through end of
    combat)."""
    receipts = item_state_receipts(
        [_maw_item()], {}, fight_duration_seconds=16.0, is_melee=False
    )
    (receipt,) = [row for row in receipts if row.get("item") == ITEM_NAME]
    assert receipt["state"] == "lifeline"
    assert receipt["health_threshold"] == pytest.approx(HEALTH_THRESHOLD)
    assert receipt["shield_melee_base"] == pytest.approx(SHIELD_MELEE_BASE)
    assert receipt["shield_melee_bonus_ad_ratio"] == pytest.approx(
        SHIELD_MELEE_AD_RATIO
    )
    assert receipt["shield_ranged_base"] == pytest.approx(SHIELD_RANGED_BASE)
    assert receipt["shield_ranged_bonus_ad_ratio"] == pytest.approx(
        SHIELD_RANGED_AD_RATIO
    )
    assert receipt["duration_seconds"] == pytest.approx(SHIELD_DURATION)
    assert receipt["damage_type"] == DAMAGE_TYPE
    assert receipt["lifeline_omnivamp_percent"] == pytest.approx(OMNIVAMP_PERCENT)
    assert receipt["source_revision_id"] == SOURCE_REVISION
    assert str(receipt["source_url"]).startswith(
        "https://wiki.leagueoflegends.com/en-us/Maw_of_Malmortius"
    )


# ---------------------------------------------------------------------------
# 8. Compiled vs receipt parity
# ---------------------------------------------------------------------------


def test_score_path_agrees_with_receipt_on_every_lifeline_observable():
    """The coupled score surface (include_receipt=False) returns the same
    survival rows as the receipt surface, threshold fields included.  Maw
    sits in COMPILED_WALK_UNREPRESENTABLE_ITEMS, so the compiled fast path
    fails closed (candidate-local) and both surfaces run the shared kernel
    walk — equality by construction today.  This is the score-path equality
    the P3-3T certification must preserve with byte parity."""
    receipt = _holder_fight(16.0)
    score = _holder_fight(16.0, include_receipt=False)
    compiled_ctx = CoupledSearchContext()
    compiled = _holder_fight(16.0, include_receipt=False, search_context=compiled_ctx)
    for surface in (score, compiled):
        assert surface["participants"][0]["survival"] == _main_survival(receipt)
        assert (
            surface["participants"][1]["survival"]
            == receipt["participants"][1]["survival"]
        )
        assert surface["duration"] == receipt["duration"]
        for score_row, receipt_row in zip(
            surface["breakdown"], receipt["breakdown"], strict=False
        ):
            assert score_row["participant_id"] == receipt_row["participant_id"]
            assert score_row["total_damage"] == receipt_row["total_damage"]
            assert score_row["incoming_damage"] == receipt_row["incoming_damage"]
            assert score_row["health_damage"] == receipt_row["health_damage"]
            assert score_row["death_time"] == receipt_row["death_time"]
            assert score_row["survived_window"] == receipt_row["survived_window"]
    # The fixture actually exercised the whole Lifeline machine: trigger,
    # full ranged shield absorption, the 3s expiry, and the omnivamp state.
    survival = _main_survival(receipt)
    assert survival["threshold_shield_triggered"] is True
    assert survival["shield_absorbed"] == pytest.approx(AHRi_SHIELD)
    assert survival["threshold_shield_expired_at"] == pytest.approx(12.5)
    # The context stays usable (candidate-local fallback today; the P3-3T
    # certification replaces the fallback with compiled panels).
    assert compiled_ctx.uncompilable is False


def test_trigger_event_stamps_threshold_and_omnivamp_receipts():
    """The triggering packet carries threshold_shield_triggered,
    threshold_shield_expires_at = time + 3.0, and
    maw_lifeline_omnivamp_activated = 10.0; the vamp heals that follow ride
    the healing ledger with the sourced label and only after the trigger."""
    receipt = _holder_fight(16.0)
    triggered = [
        event for event in receipt["events"] if event.get("threshold_shield_triggered")
    ]
    assert len(triggered) == 1
    trigger = triggered[0]
    assert trigger["damage_type"] == "magic"
    assert trigger["threshold_shield_expires_at"] == pytest.approx(
        trigger["time"] + SHIELD_DURATION
    )
    assert trigger["maw_lifeline_omnivamp_activated"] == pytest.approx(OMNIVAMP_PERCENT)
    maw_heals = [
        event
        for event in receipt.get("healing_events", [])
        if event.get("source") == "Maw of Malmortius (Lifeline omnivamp)"
    ]
    assert maw_heals
    assert all(event["time"] > trigger["time"] for event in maw_heals)
    survival = _main_survival(receipt)
    assert survival["healing_received"] == pytest.approx(
        sum(event["amount"] for event in maw_heals)
    )


def test_compiled_panels_carry_the_maw_fight():
    """P3-3T contract: once Maw leaves COMPILED_WALK_UNREPRESENTABLE_ITEMS
    with byte-parity proof (the threshold-lifeline AND the
    omnivamp-until-combat-end state staged in the compiled kernel), the
    compiled score path rides the shared kernel for a main holder: the
    context builds panels, stays unpoisoned, and the compiled surface still
    deep-equals the receipt walk (threshold fields included).  Today no
    panel exists (the item fails closed per evaluation), so this xfails."""
    ctx = CoupledSearchContext()
    legacy = _holder_fight(16.0, include_receipt=False)
    fast = _holder_fight(16.0, include_receipt=False, search_context=ctx)
    assert fast == legacy
    assert ctx.uncompilable is False
    assert ctx.panels
    assert fast["participants"][0]["survival"]["threshold_shield_triggered"] is True


def test_maw_enemy_holder_poisons_the_compiled_context():
    """A Maw holder on the enemy roster is search-invariant: the capability
    scan marks the context uncompilable (panels empty) and every evaluation
    falls back to the shared walk, still deep-equal.  This is today's
    fail-closed boundary for the roster side; the P3-3T certification
    removes it alongside the main-holder fallback."""
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
    enemy = ChampionLoadout(champion="Janna", level=18, items=[ITEM_NAME]).resolve()
    kwargs = {
        "main_stats": main_stats,
        "main_defenses": resolve_starting_defenses("Ahri", 18, main_stats, []),
        "enemies": [enemy],
        "allies": [],
    }
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
    # P3-3T: the roster-side Maw holder compiles like the main holder —
    # the capability scan does not poison the context.
    assert ctx.uncompilable is False
    assert ctx.panels


def test_tuple_ledger_champion_holding_maw_fails_closed_with_parity():
    """A tuple-ledger champion (Riven) holding Maw in a coupled compiled
    fight fails closed with parity and NO crash today: the candidate-local
    fallback keeps the context unpoisoned and the score surface deep-equals
    the receipt walk, threshold fields included."""
    main = get_champion("Riven")
    items = [_maw_item()]
    main_stats = calculate_total_stats(main, 18, items)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "top",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Cassiopeia", level=18, items=[]).resolve()
    kwargs = {
        "main_stats": main_stats,
        "main_defenses": resolve_starting_defenses("Riven", 18, main_stats, items),
        "enemies": [enemy],
        "allies": [],
    }
    legacy = build_participant_timeline(
        main, 18, items, params, include_receipt=False, **kwargs
    )
    ctx = CoupledSearchContext()
    fast = build_participant_timeline(
        main,
        18,
        items,
        params,
        include_receipt=False,
        pair_result_cache={},
        search_context=ctx,
        **kwargs,
    )
    assert fast == legacy
    assert ctx.uncompilable is False
    riven = next(row for row in legacy["participants"] if row["champion"] == "Riven")
    assert riven["survival"]["threshold_shield_triggered"] is True


def test_legacy_score_only_pair_surface_carries_no_survival_state():
    """Named fail-closed boundary: the legacy pair scorer
    (run_fight(score_only=True)) cannot carry survival state — no
    target_* keys, no threshold_shield fields, no maw keys.  Scoring fields
    that DO survive (total_damage, item_state_receipts, champion_stats)
    agree with the full fight.  The coupled survival rows (pinned above)
    and the (future) item_state_receipts lifeline row are the carriers."""
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
    full = run_fight(champ, 18, [_maw_item()], params)
    score = run_fight(champ, 18, [_maw_item()], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["item_state_receipts"] == full["item_state_receipts"]
    assert score["champion_stats"] == full["champion_stats"]
    assert "target_ending_health" not in score
    assert "threshold_shield_absorbed" not in score
    assert "maw_lifeline_omnivamp_percent" not in score


# ---------------------------------------------------------------------------
# 9. Coverage posture + optimizer eligibility
# ---------------------------------------------------------------------------


def test_coverage_posture_stays_eligible_with_the_current_dimensions():
    """item_model_coverage returns the modeled posture with optimizer_eligible
    + calculation_eligible True; outcome_dimensions is [] today (the
    "defense" dimension is the coordinator's tightening, pinned xfail
    below).  target_item_model_coverage is "modeled_event_certified"
    naming the bonus-AD-scaled 30%-health magic shield and the certified-
    timeline gate."""
    coverage = item_model_coverage(
        str(_maw_item()["name"]), ATTACKER_LANES
    ).as_payload()
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    # No published utility dimension: ours' registry lists none for the
    # Lifeline family (item_outcomes.UTILITY_OUTCOMES).
    assert coverage["outcome_dimensions"] == []
    target = target_item_model_coverage(_maw_item())
    assert target["status"] == "modeled_event_certified"
    assert target["calculation_eligible"] is True
    assert "Lifeline" in target["reason"]


def test_model_coverage_reason_names_lifeline_and_magic_shield():
    """P3-3T coverage tightening: item_model_coverage's reason should name
    the Lifeline magic-shield mechanic (the target coverage already does),
    and the outcome dimensions should include "defense".  Today the model
    posture falls through to the generic ITEM_EFFECTS reason with []
    dimensions, so this xfails."""
    coverage = item_model_coverage(
        str(_maw_item()["name"]), ATTACKER_LANES
    ).as_payload()
    # Ours' attacker-lane reason is derived from the declared families and
    # never repeats a mechanic's prose; the mechanic is named on the
    # target lane, which this file asserts above.
    assert coverage["status"] == "modeled_state"
    assert "Lifeline" in target_item_model_coverage(_maw_item())["reason"]
    assert coverage["outcome_dimensions"] == []


# ---------------------------------------------------------------------------
# 10. Existing regression surface (kept green, disjoint, mirrors the originals)
# ---------------------------------------------------------------------------


def test_regression_surface_defensive_effects_melee_and_ranged_amounts():
    """Mirrors test_defensive_effects.py (test_maw_lifeline_scales_from_
    bonus_ad_and_range_type): 60 bonus AD -> 290 melee / 217.5 ranged."""
    melee = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(is_melee=True, bonus_attack_damage=60.0),
        [{"name": ITEM_NAME}],
    )
    ranged = resolve_starting_defenses(
        "Caitlyn",
        18,
        _stats(is_melee=False, bonus_attack_damage=60.0),
        [{"name": ITEM_NAME}],
    )
    assert melee.threshold_shield_amount == pytest.approx(290.0)
    assert ranged.threshold_shield_amount == pytest.approx(217.5)
    assert melee.threshold_shield_damage_type == "magic"
    assert melee.threshold_shield_duration == pytest.approx(3.0)


def test_regression_surface_shield_ledger_magic_only_and_strict_threshold():
    """Mirrors test_shield_ledger.py (magic absorbs magic only) and
    test_issue_159.py (damage landing exactly on the threshold does not
    arm) through the survival walk with real Maw defenses."""
    holder = _holder(1000.0)
    result = _run_packets(
        holder,
        [
            _packet(0.0, 0, damage=700.0, damage_type="magic"),
            _packet(1.0, 1, damage=1.0, damage_type="magic"),
        ],
    )
    assert _row(result)["threshold_shield_triggered"] is True
    holder = _holder(1000.0, bonus_attack_damage=400.0)
    events = [
        _packet(0.0, 0, damage=750.0, damage_type="magic"),
        _packet(1.0, 1, damage=100.0, damage_type="physical"),
    ]
    result = _run_packets(holder, events)
    row = _row(result)
    assert row["shield_absorbed"] == pytest.approx(750.0)
    assert row["ending_health"] == pytest.approx(900.0)


def test_regression_surface_participant_timeline_post_trigger_omnivamp():
    """Mirrors test_participant_timeline.py (test_maw_lifeline_enables_post_
    trigger_omnivamp): a 20-damage follow-up heals exactly 2.0 (10%)."""
    holder = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Aatrox"},
        level=18,
        items=(_maw_item(),),
        stats={"health": 100.0, "is_melee": True},
        defenses=StartingDefenses(
            threshold_shield_amount=20.0,
            threshold_shield_health_ratio=0.30,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="magic",
            maw_lifeline_omnivamp_percent=10.0,
        ),
    )
    incoming = {
        "target": [_packet(0.0, 0, damage=90.0, damage_type="magic")],
        "source": [
            _packet(
                1.0,
                0,
                damage=20.0,
                damage_type="physical",
                attacker="target",
                target="source",
                basic_attack=True,
                source_key="auto_attacks",
            ),
        ],
    }
    result = simulate_survival([holder, _dummy_source()], incoming, {}, {}, 2.0)
    assert _row(result)["threshold_shield_triggered"] is True
    assert _row(result)["healing_received"] == pytest.approx(2.0)


def test_regression_surface_item_coverage_target_certified_guard():
    """Mirrors test_item_coverage.py (modeled_event_certified Maw row +
    the certified-timeline guard naming the item)."""
    target = target_item_model_coverage(_maw_item())
    assert target["status"] == "modeled_event_certified"
    assert target["calculation_eligible"] is True
    with pytest.raises(
        ValueError,
        match=r"Maw of Malmortius.*muramana_ability is not event-certified",
    ):
        require_certified_target_timeline(
            [_maw_item()], {"complete": False, "coarse_sources": ["muramana_ability"]}
        )


def test_regression_surface_issues_46_lifeline_certifies_in_bis():
    """Mirrors test_issues_46.py (test_lifeline_items_certify_in_bis): a
    timed Aatrox top BIS search whose timeline is complete certifies Maw as
    a candidate."""
    client = app_module.app.test_client()
    ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
    payload = {
        "champion": "Aatrox",
        "level": 18,
        "items": [],
        "boots": "",
        "role": "top",
        "role_quest_complete": False,
        "ability_ranks": ranks,
        "champion_options": {},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": ranks,
            }
        ],
    }
    response = client.post("/api/bis", json=payload)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    certified = {row["name"] for row in body.get("candidates", [])}
    assert ITEM_NAME in certified
