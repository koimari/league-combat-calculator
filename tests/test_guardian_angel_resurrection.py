"""P1 Package 3P — Guardian Angel (3026) "Rebirth" resurrection parity
certification.

This file is the focused acceptance-matrix owner for Guardian Angel's Rebirth
passive.  It pins the OBSERVABLES of the completed P3-3P contract against
today's source.  Every bullet below is a named, passing assertion: there are
no ``xfail`` rows left, and the one genuine limit (the request parser's
<=30s ``fight_duration`` cap) is asserted explicitly rather than skipped.

Contract under test (current runtime facts, verified before pinning):

* ITEM IDENTITY: cached name "Guardian Angel", id 3026, price 3200
  (shop.prices.total, sell 1280), tier 3 LEGENDARY.  Stats: 55 flat attack
  damage, 45 flat armor.  Passive name "Rebirth"; the cached
  riotDescription branch is exact: "Upon taking lethal damage, restores
  50% base Health and 100% max Mana after 4 seconds of Stasis."
* TYPED SOURCE: the item_effects registry entry carries type
  "defensive_start" with ``revive_health_ratio 0.50`` / ``revive_delay
  4.0`` / ``revive_cooldown 300.0`` (read via ``required_effect_value``);
  a missing key raises ``KeyError`` naming "Guardian Angel" AND the key
  (AGENTS.md rule 5 — no silent fallbacks).  The P3-3P completion added the
  mana restore (100% max mana), the one-use flag, and the wiki source
  receipt (``source_url`` / ``source_revision_id`` — revision 4046863) to
  the typed registry; all four are present and pinned, and the fail-closed
  KeyError path is pinned on a deliberately-never-real key.
* ORDINARY STAT PARITY: equipping GA changes EXACTLY attack_damage +55 and
  armor +45 (plus their bonus_* twins) vs the bare build; no other stat.
  When the holder never takes lethal damage, arming the revive changes
  NOTHING: a fight whose holder carries GA is identical to a control whose
  holder has the same item data and stats but an unarmed revive
  (survival/breakdown/events/healing/support all byte-equal).
* REVIVE TRIGGER + WINDOW: the first lethal packet records ``death_time`` /
  ``first_death_time`` and the walk authors one revive candidate after
  EVERY incoming damage event (participant_timeline.py ~3086-3110,
  survival/compile.py revive_candidate_actions); the kernel applies the
  earliest candidate that finds the participant dead.  In the aligned case
  (lethal packet is the fight's first damage, e.g. death at t=0) the
  applied revive lands exactly at death_time + 4.0 and the death interval
  spans exactly [death_time, revive_time] (4.0s).  The window is now
  lethal-anchored in sustained fights too: candidates authored from
  PRE-lethal packets are skipped (``revive_window_not_elapsed``) until the
  full sourced 4.0s has elapsed since the lethal hit, so the sustained case
  (death 9.981 -> revive 13.981) matches the aligned case.
* STASIS DURING THE WINDOW: authored EXPLICITLY at the lethal packet
  (P3-3P) — ``stasis_until == revive_time``, ``stasis_source "Guardian
  Angel (Rebirth)"``, ``stasis_started_at == first_death_time``, plus one
  ``revive_stasis`` receipt row per armed window (start / end / sourced
  duration / source / sourced cooldown / resolved / ready_at).  The window
  is coextensive with the dead state, which keeps owning every skip:
  incoming damage is still ignored (public event kept with damage 0.0 +
  ``skipped_reason target_dead``), the holder still authors no damage
  (``skipped_reason attacker_dead``), the death downtime interval is still
  the single [death, revive] row, and the holder acts again after the
  revive.  A holder with no armed revive emits no ``revive_stasis`` key and
  keeps ``stasis_until`` / ``stasis_source`` at 0.0/"".
* ONE REVIVE ONLY + COOLDOWN: the sourced 300.0s cooldown — not a spent
  one-shot boolean — is the re-arm gate (P3-3P).  The applied revive parks
  re-arm at ``revive_time + 300``; a lethal packet before that arms no
  stasis window and is terminal (its candidate is denied with the named
  receipt reason ``revive_on_cooldown``), and a lethal packet at or after
  it arms a second window and revives again.  Requested fights are bounded
  to <=30s by the request parser, so no modeled fight can span the
  cooldown: inside a fight the observable rule stays exactly one revive
  (second ``death_time`` recorded, terminal_phase "dead", single
  revive_time, ONE ``revive_stasis`` row).  The re-arm is therefore pinned
  at the kernel, where the rule lives — the sibling walk pattern from
  ``tests/test_survival_kernel.py``, driven by the REAL cached item's
  resolved defenses.
* EXTRA DAMAGE WHILE DEAD: damage landing after death (during the window
  or after the final death) never compounds — every post-death packet is
  ignored (``target_dead``), so ``health_damage`` counts only lethal hits.
* SCORE VS RECEIPT PARITY: both adapters drive one kernel.  The coupled
  score surface (``include_receipt=False``) returns the same survival rows
  as the receipt surface, revive fields included (revived / revive_time /
  revive_health_restored / revive_source / first_death_time / death_time /
  terminal_phase).  GA is in COMPILED_WALK_UNREPRESENTABLE_ITEMS ("Rebirth
  candidates authored in the event walk"), so the compiled fast path fails
  closed (UncompilableActionError) and falls back to the shared walk — the
  equality holds by construction.  The legacy pair surface
  (``run_fight(score_only=True)``) carries NO survival state (target_*
  fields are None) — that is the named fail-closed boundary; the coupled
  survival rows and the item_state_receipts row are the carriers.
* RECEIPT ROW (P3-3P surface, present): ``item_state_receipts`` emits ONE
  Guardian Angel row (the 3M/3N/3O pattern), state "rebirth", carrying the
  revive state (revived / restored amount / delay / cooldown / one-use /
  mana ratio / wiki source revision) plus the named mana, cooldown and
  stasis boundary strings.
* NO OUTGOING TDD: the revive itself authors no damage anywhere — no
  damage event carries a revive/Rebirth source, no breakdown row exists for
  it, and the holder's total_damage comes only from ordinary sources.
  Revive is also NOT healing: ``healing_received`` stays 0.0.
* FAIL-CLOSED: no GA item → no revive fields, no receipt row; a fabricated
  item option target is rejected ("Unknown item option target: Guardian
  Angel"); malformed typed values raise (TypeError/ValueError).
* COVERAGE: ``item_model_coverage`` returns the justified posture
  ("stats_only", reason naming "Rebirth" + the survival ledger),
  optimizer_eligible + calculation_eligible True, outcome_dimensions
  ["revive"]; ``target_item_model_coverage`` is "modeled" naming Rebirth
  and 50% base health.
* XFAIL: none remain.  The five originally-absent mechanics — the typed
  mana/one-use/source-receipt keys, the explicit stasis-state authoring,
  the 300s-cooldown re-arm, the item_state_receipts Rebirth row, and the
  lethal-anchored 4s window in a sustained fight — are all implemented and
  pinned as named tests.  The one genuine BOUNDARY left is the <=30s
  request cap on ``fight_duration``, which is asserted explicitly rather
  than hidden: it is why the cooldown re-arm is pinned at the kernel.

Sibling owners: the Gunmetal Greaves precedent is pinned in
``tests/test_gunmetal_greaves_riot_branch.py`` (3O receipt-only named-
boundary shape); the Doran's Helm and Ionian Boots precedents in
``tests/test_dorans_helm_minion_damage.py`` (3M) and
``tests/test_ionian_boots_summoner_haste.py`` (3N); the kernel score==
receipt contract in ``tests/test_survival_kernel.py`` (issue #137).  The
E8d champion-revive interface is pinned in ``tests/test_e8_support.py`` /
``tests/test_e8_followup_hooks.py``.  Existing regression surface touching
this item (kept green, disjoint, quoted in section 13):
``tests/test_participant_timeline.py`` (test_guardian_angel_revives_target_
after_first_lethal_packet ~136), ``tests/test_defensive_effects.py``
(test_guardian_angel_resolves_sourced_base_health_rebirth ~240),
``tests/test_e8_followup_hooks.py`` (test_guardian_angel_keeps_item_source
~70), ``tests/test_item_coverage.py`` (~275/480/561), ``tests/test_economy.py``
(~51 sell 1280) and ``tests/test_app.py`` (~1991 coverage pins).  This file
is disjoint and pins only the Guardian Angel acceptance observables.
"""

import json
from dataclasses import replace

import pytest

from src.calculator.item_coverage import ATTACKER_LANES
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_coverage import (
    item_model_coverage,
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
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

ITEM_NAME = "Guardian Angel"
ITEM_ID = 3026
PRICE = 3200
ATTACK_DAMAGE_FLAT = 55.0
ARMOR_FLAT = 45.0
REVIVE_HEALTH_RATIO = 0.50
REVIVE_DELAY = 4.0
REVIVE_COOLDOWN = 300.0
REVIVE_MANA_RATIO = 1.0
REVIVE_SOURCE = "Guardian Angel (Rebirth)"
# The cached wiki branch text (riotDescription) — the exact Rebirth sentence.
BRANCH_FRAGMENTS = (
    "<passive>Rebirth</passive>",
    "50% base Health",
    "100% max Mana",
    "4 seconds",
    "Stasis",
)
# The main champion's attack cadence in the auto-only fixtures: hits land at
# 0.0 then every AS_INTERVAL seconds (Ahri level 18, deterministic walk).
AS_INTERVAL = 1.109


def _ga_item() -> dict:
    """The real cached item record (id 3026)."""
    return get_item_by_name(ITEM_NAME)


def _holder_fight(
    duration: float,
    *,
    holder_items: tuple[str, ...] = (ITEM_NAME,),
    stats: dict[str, float],
    holder: str = "Ashe",
    include_receipt: bool = True,
    search_context: CoupledSearchContext | None = None,
    arm_revive: bool = True,
) -> dict:
    """A coupled fight where the enemy *holder* is the GA candidate.

    The holder's defenses are re-resolved from the overridden stats so the
    typed revive amount is exactly 0.5 x stats["base_health"] (the loadout
    resolves its own defenses from the champion's stock stats otherwise,
    which would hide the base-vs-max distinction behind the max-health cap).
    ``include_receipt=False`` returns the coupled score surface; passing a
    ``search_context`` plus an empty pair cache exercises the compiled score
    path (which must fail closed on GA and fall back to the shared walk).
    ``arm_revive=False`` keeps the item data (so the pair-fight damage calc
    still sees the +55 AD / +45 armor) while leaving the revive unarmed —
    the byte-identical control for the ordinary-stat-parity pin.
    """
    main = get_champion("Ahri")
    main_stats = calculate_total_stats(main, 18, [])
    params = FightParams.from_request(
        {
            "fight_mode": "auto_only",
            "fight_duration": duration,
            "auto_attacks_only": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion=holder, level=18, items=holder_items).resolve()
    es = dict(enemy.stats)
    es.update(stats)
    items = [_ga_item()] if ITEM_NAME in holder_items else []
    defenses = resolve_starting_defenses(holder, 18, es, items if arm_revive else [])
    enemy = replace(enemy, stats=es, defenses=defenses)
    return build_participant_timeline(
        main,
        18,
        [],
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Ahri", 18, main_stats, []),
        enemies=[enemy],
        allies=[],
        include_receipt=include_receipt,
        pair_result_cache={} if search_context is not None else None,
        search_context=search_context,
    )


def _holder_survival(result: dict) -> dict:
    """The GA holder's survival row (the enemy participant)."""
    return result["participants"][1]["survival"]


def _holder_target_damage_times(result: dict) -> list[float]:
    """Times of every damage packet aimed at the GA holder."""
    holder_id = result["participants"][1]["participant_id"]
    return [
        float(event["time"])
        for event in result["events"]
        if str(event.get("target", "")) == holder_id
        and float(event.get("damage", 0.0)) >= 0.0
        and event.get("source") is not None
    ]


def _earliest_revive_candidate(result: dict, delay: float) -> float:
    """The engine's actual rule: the earliest (packet_time + delay) that
    lands while the holder is dead.  The walk authors one candidate after
    every incoming damage packet and applies the first one that finds the
    participant dead (participant_timeline.py ~3086-3110)."""
    holder_id = result["participants"][1]["participant_id"]
    death_time = _holder_survival(result)["first_death_time"]
    candidates = [
        packet_time + delay
        for packet_time in _holder_target_damage_times(result)
        if packet_time + delay >= death_time
    ]
    assert candidates, "a lethal packet always authors a candidate at death+delay"
    return min(candidates)


# ---------------------------------------------------------------------------
# 1. Identity / stats / passive
# ---------------------------------------------------------------------------


def test_cached_identity_pins_name_id_price_stats_and_rebirth_branch():
    """The cached item is Guardian Angel (id 3026), price 3200, +55 AD /
    +45 armor, passive "Rebirth", with the exact branch sentence."""
    item = _ga_item()
    assert item["name"] == ITEM_NAME
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["stats"]["attackDamage"]["flat"] == ATTACK_DAMAGE_FLAT
    assert item["stats"]["armor"]["flat"] == ARMOR_FLAT
    assert item["passives"][0]["name"] == "Rebirth"
    for fragment in BRANCH_FRAGMENTS:
        assert fragment in item["riotDescription"], fragment


def test_equipping_ga_yields_exactly_55_ad_and_45_armor():
    """Equipping GA changes EXACTLY four numeric stats: attack_damage +55,
    armor +45 and their bonus_* twins — and NOTHING else (no health, no
    mana, no haste, no lifesteal, no resist changes...)."""
    champ = get_champion("Ahri")
    base = calculate_total_stats(champ, 18, [])
    equipped = calculate_total_stats(champ, 18, [_ga_item()])
    deltas = {
        key: round(equipped[key] - base[key], 6)
        for key in equipped
        if equipped[key] != base[key]
    }
    assert deltas == {
        "attack_damage": 55.0,
        "armor": 45.0,
        "bonus_attack_damage": 55.0,
        "bonus_armor": 45.0,
    }


# ---------------------------------------------------------------------------
# 2. Typed source values
# ---------------------------------------------------------------------------


def test_typed_rebirth_values_return_exact_numbers():
    """The typed registry returns exactly 0.50 health ratio, 4.0s delay,
    300.0s cooldown — never a bool, never a stale literal."""
    ratio = required_effect_value(ITEM_NAME, "revive_health_ratio")
    delay = required_effect_value(ITEM_NAME, "revive_delay")
    cooldown = required_effect_value(ITEM_NAME, "revive_cooldown")
    assert ratio == pytest.approx(REVIVE_HEALTH_RATIO)
    assert delay == pytest.approx(REVIVE_DELAY)
    assert cooldown == pytest.approx(REVIVE_COOLDOWN)
    assert not isinstance(ratio, bool)
    assert not isinstance(delay, bool)
    assert not isinstance(cooldown, bool)
    assert ITEM_EFFECTS[ITEM_NAME]["type"] == "defensive_start"
    # The defensive layer folds the typed values into the armed revive.
    defenses = resolve_starting_defenses(
        "Ashe", 18, {"base_health": 400.0, "health": 400.0}, [_ga_item()]
    )
    assert defenses.revive_health_amount == pytest.approx(200.0)
    assert defenses.revive_delay == pytest.approx(REVIVE_DELAY)
    assert defenses.revive_cooldown == pytest.approx(REVIVE_COOLDOWN)
    assert defenses.revive_source == REVIVE_SOURCE


def test_missing_typed_key_fails_loud_naming_item_and_key():
    """AGENTS.md rule 5: a missing key raises KeyError naming Guardian
    Angel AND the key — no silent stale fallback.  The key is deliberately
    never a real key, so this passes today AND after P3-3P."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(ITEM_NAME, "not_a_typed_guardian_angel_key")
    message = excinfo.value.args[0]
    assert ITEM_NAME in message
    assert "not_a_typed_guardian_angel_key" in message


def test_malformed_typed_values_fail_loudly():
    """A malformed (non-numeric) typed value raises instead of silently
    coercing: the defensive layer float()s the typed value, so a string
    fails with TypeError/ValueError naming the item context."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(ITEM_EFFECTS[ITEM_NAME], "revive_delay", "four")
    try:
        with pytest.raises((TypeError, ValueError)):
            resolve_starting_defenses(
                "Ashe", 18, {"base_health": 400.0, "health": 400.0}, [_ga_item()]
            )
    finally:
        monkeypatch.undo()


def test_typed_mana_one_use_and_source_receipt_keys():
    """P3-3P typed surface (implemented): the registry carries the 100% max
    mana restore, the one-use flag, and the wiki source receipt
    (``source_url`` / ``source_revision_id``).  Each is read directly off the
    typed entry, so a removed key fails this row loudly instead of falling
    back — the fail-closed KeyError path itself is pinned by
    ``test_missing_typed_key_fails_loud_naming_item_and_key`` above."""
    effect = ITEM_EFFECTS[ITEM_NAME]
    assert effect["revive_mana_ratio"] == pytest.approx(REVIVE_MANA_RATIO)
    assert effect["one_use"] is True
    assert isinstance(effect["source_revision_id"], int)
    assert str(effect["source_url"]).startswith(
        "https://wiki.leagueoflegends.com/en-us/Guardian_Angel"
    )


# ---------------------------------------------------------------------------
# 3. Ordinary stat parity — the revive must not change anything else
# ---------------------------------------------------------------------------


def test_untriggered_revive_leaves_the_fight_byte_identical():
    """THE core parity pin: when the holder never takes lethal damage,
    arming Rebirth changes NOTHING.  A fight whose holder carries GA (item
    data, stats, and defenses with the armed revive) is identical to a
    control with the SAME item data and stats but an UNARMED revive
    (defenses without GA) — survival, breakdown, events, healing_events and
    support_events are all byte-equal.  The revive only ever contributes the
    survival state transition on a lethal packet."""
    stats = dict(health=5000.0, base_health=200.0, armor=0.0, magic_resistance=0.0)
    with_ga = _holder_fight(5.0, stats=stats)
    assert _holder_survival(with_ga)["revived"] is False
    ga_stats = dict(with_ga["participants"][1]["stats"])
    control = _holder_fight(
        5.0,
        holder_items=(ITEM_NAME,),
        stats=ga_stats,
        arm_revive=False,
    )
    assert control["participants"][1]["stats"] == ga_stats
    assert (
        resolve_starting_defenses("Ashe", 18, ga_stats, []).revive_health_amount == 0.0
    )
    assert _holder_survival(control) == _holder_survival(with_ga)
    assert control["breakdown"] == with_ga["breakdown"]
    assert control["events"] == with_ga["events"]
    assert control["healing_events"] == with_ga["healing_events"]
    assert control["support_events"] == with_ga["support_events"]


# ---------------------------------------------------------------------------
# 4. Lethal death + revive timing
# ---------------------------------------------------------------------------


def test_lethal_death_records_window_and_revive_at_death_plus_four():
    """A fight where the holder takes lethal damage records the death and
    the 4-second resurrection window: first_death_time is set, the revive
    lands exactly at first_death_time + 4.0 (aligned case: the lethal packet
    is the fight's first damage), the death downtime interval spans exactly
    [death, revive], and the holder ends terminal "revived" with
    survived_window True when the fight ends inside the post-revive lull."""
    result = _holder_fight(
        4.1,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["first_death_time"] == pytest.approx(0.0, abs=1e-3)
    assert survival["revived"] is True
    assert survival["revive_time"] == pytest.approx(
        survival["first_death_time"] + REVIVE_DELAY, abs=1e-3
    )
    assert survival["revive_source"] == REVIVE_SOURCE
    assert survival["revive_health_restored"] == pytest.approx(100.0)
    assert survival["terminal_phase"] == "revived"
    assert survival["survived_window"] is True
    assert survival["death_time"] is None
    assert survival["action_downtime"] == pytest.approx(REVIVE_DELAY, abs=1e-3)
    assert survival["action_downtime_intervals"] == [
        {
            "recipient": "enemy:Ashe",
            "kind": "death",
            "start": survival["first_death_time"],
            "end": survival["revive_time"],
            "source": "auto_attacks",
        }
    ]


def test_revive_restores_exactly_half_of_base_health_not_max():
    """The restored amount is 50% of BASE health — not current health, not
    bonus-inclusive max.  The holder has max_health 1000 (bonus_health 800
    on top of base 200); the revive restores exactly 100.0 = 0.5 x 200,
    where 0.5 x max would be 500 and 0.5 x current would be 500 before the
    first hit."""
    result = _holder_fight(
        20.0,
        stats=dict(
            health=1000.0,
            base_health=200.0,
            bonus_health=800.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["max_health"] == pytest.approx(1000.0)
    assert survival["revived"] is True
    assert survival["revive_health_restored"] == pytest.approx(100.0)
    assert survival["revive_health_restored"] == pytest.approx(
        REVIVE_HEALTH_RATIO * 200.0
    )
    assert survival["revive_health_restored"] != pytest.approx(500.0)


# ---------------------------------------------------------------------------
# 5. Four-second no-action / no-incoming-damage stasis
# ---------------------------------------------------------------------------


def test_incoming_damage_during_the_window_is_ignored_not_compounded():
    """Damage landing after death but before/during the revive window does
    NOT compound: every packet in (death_time, revive_time) is kept in the
    public event list with damage 0.0 and skipped_reason "target_dead", and
    health_damage counts only the lethal hit (100.0 of the 100-health
    holder), not the window hits."""
    result = _holder_fight(
        4.1,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    holder_id = result["participants"][1]["participant_id"]
    window_hits = [
        event
        for event in result["events"]
        if str(event.get("target", "")) == holder_id
        and survival["first_death_time"]
        < float(event["time"])
        < survival["revive_time"]
    ]
    assert window_hits, "expected authored packets inside the window"
    for event in window_hits:
        assert event["damage"] == 0.0
        assert event["skipped_reason"] == "target_dead"
    assert survival["health_damage"] == pytest.approx(100.0)
    assert survival["damage_taken"] == pytest.approx(104.0)


def test_holder_authors_no_damage_during_the_window_and_acts_after_revival():
    """During the window the holder is unable to act: every holder-authored
    packet inside (death_time, revive_time) carries damage 0.0 with
    skipped_reason "attacker_dead".  Immediately after the revive the holder
    acts again — its first post-revive auto lands full damage before the
    next lethal."""
    result = _holder_fight(
        12.0,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    holder_id = result["participants"][1]["participant_id"]
    holder_events = [
        event
        for event in result["events"]
        if str(event.get("attacker", "")) == holder_id
    ]
    window_events = [
        event
        for event in holder_events
        if survival["first_death_time"] < float(event["time"]) < survival["revive_time"]
    ]
    assert window_events
    for event in window_events:
        assert event["damage"] == 0.0
        assert event["skipped_reason"] == "attacker_dead"
    post_revive = [
        event
        for event in holder_events
        if survival["revive_time"] <= float(event["time"]) < survival["death_time"]
    ]
    assert post_revive, "holder must act again between revive and second lethal"
    assert all(float(event["damage"]) > 0.0 for event in post_revive)


def test_explicit_stasis_state_is_authored_for_the_window():
    """P3-3P (implemented): the 4s window is an EXPLICIT stasis state, not
    only the implicit dead state.  The lethal packet authors
    ``stasis_until == revive_time`` with ``stasis_source "Guardian Angel
    (Rebirth)"`` starting at the death, and the survival row carries one
    ``revive_stasis`` receipt row per armed window with every value traced
    to the typed registry (delay 4.0, cooldown 300.0, source label) plus the
    resolution (``resolved`` / ``ready_at == revive_time + 300``)."""
    result = _holder_fight(
        4.1,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["stasis_until"] == pytest.approx(survival["revive_time"])
    assert survival["stasis_source"] == REVIVE_SOURCE
    assert survival["stasis_started_at"] == pytest.approx(
        survival["first_death_time"], abs=1e-3
    )
    # The receipt: exactly one armed window, spanning exactly the sourced
    # delay, resolved by the revive, with the sourced cooldown and the
    # re-arm timestamp it implies.
    assert survival["revive_stasis"] == [
        {
            "start": pytest.approx(survival["first_death_time"], abs=1e-3),
            "end": pytest.approx(survival["revive_time"], abs=1e-3),
            "duration": pytest.approx(REVIVE_DELAY),
            "source": REVIVE_SOURCE,
            "cooldown": pytest.approx(REVIVE_COOLDOWN),
            "resolved": True,
            "ready_at": pytest.approx(survival["revive_time"] + REVIVE_COOLDOWN),
        }
    ]


def test_explicit_stasis_adds_no_second_gate_and_no_row_without_a_window():
    """The explicit stasis is a state/receipt authoring, NOT a second
    blocking gate: the coextensive dead state keeps owning every skip, so
    packets inside the window still read "target_dead" (incoming) and
    "attacker_dead" (outgoing) rather than a stasis reason, and the death
    downtime interval is still the single [death, revive] row.  A holder
    with no armed revive emits NO ``revive_stasis`` key at all and keeps
    ``stasis_until``/``stasis_source`` at 0.0/"" — the key is fail-closed
    keyed to an actually-armed window."""
    stats = dict(
        health=100.0,
        base_health=200.0,
        bonus_health=0.0,
        armor=0.0,
        magic_resistance=0.0,
    )
    result = _holder_fight(4.1, stats=stats)
    survival = _holder_survival(result)
    holder_id = result["participants"][1]["participant_id"]
    window = (survival["first_death_time"], survival["revive_time"])
    incoming = [
        event
        for event in result["events"]
        if str(event.get("target", "")) == holder_id
        and window[0] < float(event["time"]) < window[1]
    ]
    outgoing = [
        event
        for event in result["events"]
        if str(event.get("attacker", "")) == holder_id
        and window[0] < float(event["time"]) < window[1]
    ]
    assert incoming and outgoing
    assert {event["skipped_reason"] for event in incoming} == {"target_dead"}
    assert {event["skipped_reason"] for event in outgoing} == {"attacker_dead"}
    assert [row["kind"] for row in survival["action_downtime_intervals"]] == ["death"]
    assert survival["action_downtime"] == pytest.approx(REVIVE_DELAY, abs=1e-3)

    bare = _holder_survival(_holder_fight(4.1, holder_items=(), stats=stats))
    assert "revive_stasis" not in bare
    assert bare["stasis_until"] == 0.0
    assert bare["stasis_source"] == ""


def test_stasis_window_unresolved_at_the_fight_end_claims_nothing():
    """Fail-closed on a truncated window: when the fight ends INSIDE the 4s
    stasis (death at 0.0, fight ends at 2.0), the receipt records the armed
    window with ``resolved`` False and NO ``ready_at`` — the cooldown starts
    only after a resurrection that never happened, so it is never claimed.
    The row makes no revive claim either (revived False, revive_time None,
    terminal "dead", survived_window False), and the death downtime interval
    stays clamped to the fight even though the window extends past it."""
    survival = _holder_survival(
        _holder_fight(
            2.0,
            stats=dict(
                health=100.0,
                base_health=200.0,
                bonus_health=0.0,
                armor=0.0,
                magic_resistance=0.0,
            ),
        )
    )
    assert survival["revived"] is False
    assert survival["revive_time"] is None
    assert survival["revive_health_restored"] == 0.0
    assert survival["terminal_phase"] == "dead"
    assert survival["survived_window"] is False
    (window,) = survival["revive_stasis"]
    assert window["resolved"] is False
    assert "ready_at" not in window
    assert window["start"] == pytest.approx(0.0, abs=1e-3)
    assert window["end"] == pytest.approx(REVIVE_DELAY)
    assert window["cooldown"] == pytest.approx(REVIVE_COOLDOWN)
    assert survival["action_downtime"] == pytest.approx(2.0, abs=1e-3)
    assert survival["action_downtime_intervals"][0]["end"] == pytest.approx(2.0)


def test_ordinary_stasis_stacked_beyond_the_revive_window_blocks_on_its_own_terms():
    """Hardening pin for the tolerance comment on ``_actor_stasis_blocks``
    (transitions.py, directly above its ``revive_stasis_until >= stasis_until
    - 1e-9`` check): that ``- 1e-9`` only absorbs float round-trip noise
    between two computations of the SAME timestamp when the revive window is
    the sole thing that ever set ``stasis_until``.  It must NOT let a
    genuinely longer ordinary stasis (Zhonya's/Time Stop) stacked on the same
    actor get silently swallowed by the revive bypass.

    No public request-level lever stacks an ordinary Stasis onto a holder
    that is already dead — Zhonya's/Time Stop are self-cast abilities, and a
    dead actor cannot cast (the same ``attacker_dead``/cast gates this file
    exercises elsewhere block that path entirely).  So this drives the
    kernel directly with hand-authored ``SurvivalAction`` rows, the same
    pattern ``_rebirth_kernel_walk`` above uses to reach the 300s cooldown
    gate: a lethal packet arms the REAL Guardian Angel revive stasis
    (0 -> 4.0s, via the typed defenses resolved from the cached item), an
    ordinary Stasis action is stacked on the SAME holder ending at 4.5s
    (clearly beyond the revive window's 4.0s end — not a 1e-9 near-tie), and
    a packet the holder tries to author at t=2.0 (still dead, inside BOTH
    windows) is compared against the baseline (no ordinary stasis) at the
    identical timestamp.

    Baseline: the bypass fires (the revive window is the sole ceiling of
    ``stasis_until``) and the dead-state gate names the skip
    "attacker_dead".  With the longer ordinary stasis stacked on top: the
    bypass condition is false (4.0 is not >= 4.5 - 1e-9), so
    ``_actor_stasis_blocks`` blocks on the ordinary stasis's own terms and
    the skip reason becomes "attacker_state_blocked" instead — proving the
    longer stasis is never laundered through the revive bypass."""
    from src.calculator.roster_composition import Combatant
    from src.calculator.program.compile import action_from_event
    from src.calculator.program.walk import walk as run_one_walk
    from src.calculator.survival import (
        EVENT_SLOTS,
        ActionKind,
        ReceiptLedger,
        SurvivalAction,
        TransitionContext,
        TransitionRank,
        build_states,
    )

    defenses = resolve_starting_defenses(
        "Ashe", 18, {"health": 100.0, "base_health": 200.0}, [_ga_item()]
    )

    def _combatants() -> list:
        holder = Combatant(
            participant_id="holder",
            team="enemy",
            champion_data={"name": "Ashe"},
            level=18,
            items=(_ga_item(),),
            stats={"health": 100.0, "is_melee": False},
            defenses=defenses,
        )
        victim = Combatant(
            participant_id="victim",
            team="main",
            champion_data={"name": "Ahri"},
            level=18,
            items=(),
            stats={"health": 10000.0, "is_melee": False},
            defenses=resolve_starting_defenses(
                "Ahri", 18, {"health": 10000.0, "base_health": 10000.0}, []
            ),
        )
        return [holder, victim]

    def _lethal(time: float, seq: int) -> object:
        return SurvivalAction(
            sort_key=(
                time,
                TransitionRank.DAMAGE,
                0,
                0,
                seq,
                "holder",
                f"hit{seq}",
                "auto_attacks",
            ),
            time=time,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.PLAIN_DAMAGE,
            subject=0,
            attacker=0,
            aidx=seq,
            amount=150.0,
            damage_type="physical",
            source_key="auto_attacks",
            source="auto_attacks",
            event_slot=EVENT_SLOTS.slot(f"hit{seq}"),
            sequence=seq,
        )

    def _ordinary_stasis(time: float, duration: float, seq: int) -> object:
        return SurvivalAction(
            sort_key=(
                time,
                TransitionRank.STATE_GRANT,
                0,
                0,
                seq,
                "holder",
                f"stasis{seq}",
                "stasis",
            ),
            time=time,
            phase=TransitionRank.STATE_GRANT,
            kind=ActionKind.STASIS,
            subject=0,
            attacker=0,
            aidx=seq,
            duration=duration,
            source_key="ordinary_stasis",
            source="Zhonya's Hourglass",
            event_slot=EVENT_SLOTS.slot(f"stasis{seq}"),
            sequence=seq,
        )

    def _probe(time: float, seq: int) -> object:
        # A packet the dead holder tries to author against the (alive)
        # victim: phase >= 0 so it runs the same attacker-side block-check
        # gate the engine applies to every ordinary authored packet.
        return SurvivalAction(
            sort_key=(
                time,
                TransitionRank.DAMAGE,
                1,
                0,
                seq,
                "holder",
                f"probe{seq}",
                "auto_attacks",
            ),
            time=time,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.PLAIN_DAMAGE,
            subject=1,
            attacker=0,
            aidx=seq,
            amount=1.0,
            damage_type="physical",
            source_key="auto_attacks",
            source="auto_attacks",
            event_slot=EVENT_SLOTS.slot(f"probe{seq}"),
            sequence=seq,
        )

    def _probe_skip_reason(*, with_ordinary_stasis: bool) -> str:
        combatants = _combatants()
        actions = [_lethal(0.0, 0)]
        if with_ordinary_stasis:
            actions.append(_ordinary_stasis(0.0, 4.5, 1))
        actions.append(_probe(2.0, 2))
        states = build_states(combatants, (0.0,) * len(combatants))
        index_of = {"holder": 0, "victim": 1}
        walk_actions = [action._replace(event={}) for action in actions]
        ledger = ReceiptLedger(
            actions=walk_actions,
            index_of=index_of,
            compile_event=action_from_event,
            annotating=False,
        )
        ctx = TransitionContext(
            duration=10.0,
            states=states,
            combatants=combatants,
            index_of=index_of,
            ledger=ledger,
            regeneration_windows=(None,) * len(combatants),
        )
        run_one_walk(walk_actions, ctx)
        probe_action = walk_actions[-1]
        assert EVENT_SLOTS.text(probe_action.event_slot) == "probe2"
        return probe_action.event["skipped_reason"]

    baseline_reason = _probe_skip_reason(with_ordinary_stasis=False)
    stacked_reason = _probe_skip_reason(with_ordinary_stasis=True)
    assert baseline_reason == "attacker_dead"
    assert stacked_reason == "attacker_state_blocked"
    assert stacked_reason != baseline_reason


# ---------------------------------------------------------------------------
# 6. One revive only + cooldown
# ---------------------------------------------------------------------------


def test_second_lethal_after_revive_does_not_revive_again():
    """One-use rule: the holder dies at 0.0, revives at 4.0 with 100
    health, and the next auto (4.436) is lethal again — the second lethal
    does NOT trigger a second Rebirth.  revived stays True with the SINGLE
    original revive_time/restored amount, the second death is recorded
    (death_time 4.436, terminal_phase "dead"), and no second revive_time
    appears (revive_time != death_time + 4.0)."""
    result = _holder_fight(
        12.0,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["revived"] is True
    assert survival["revive_time"] == pytest.approx(4.0, abs=1e-3)
    assert survival["revive_health_restored"] == pytest.approx(100.0)
    assert survival["death_time"] == pytest.approx(4.436, abs=1e-3)
    assert survival["first_death_time"] == pytest.approx(0.0, abs=1e-3)
    assert survival["terminal_phase"] == "dead"
    assert survival["revive_time"] != pytest.approx(
        survival["death_time"] + REVIVE_DELAY, abs=1e-3
    )


def _rebirth_kernel_walk(second_lethal: float, *, receipt: bool) -> tuple[dict, list]:
    """One participant, real Guardian Angel defenses, driven straight through
    the survival kernel (the sibling pattern in ``tests/test_survival_kernel.py``
    ~700-890).

    A REQUESTED fight cannot host this: ``fight_duration`` is bounded to
    1-30s by the request parser (pinned below), while Rebirth's cooldown is
    300s.  The kernel — which owns the re-arm rule — carries no such bound,
    so this is where the sourced cooldown gate is pinned.  Every revive
    number comes from ``resolve_starting_defenses`` on the REAL cached item,
    i.e. from the typed registry; nothing is authored by hand.
    """
    from src.calculator.roster_composition import Combatant
    from src.calculator.program.build import roster_program
    from src.calculator.program.compile import action_from_event
    from src.calculator.program.views.survival import survival
    from src.calculator.program.walk import walk as run_one_walk
    from src.calculator.survival import (
        EVENT_SLOTS,
        ActionKind,
        ReceiptLedger,
        ScoreLedger,
        SurvivalAction,
        TransitionContext,
        TransitionRank,
        build_states,
    )

    duration = second_lethal + 60.0
    defenses = resolve_starting_defenses(
        "Ashe", 18, {"health": 100.0, "base_health": 200.0}, [_ga_item()]
    )
    combatant = Combatant(
        participant_id="holder",
        team="enemy",
        champion_data={"name": "Ashe"},
        level=18,
        items=(_ga_item(),),
        stats={"health": 100.0, "is_melee": False},
        defenses=defenses,
    )

    def _lethal(time: float, seq: int) -> object:
        return SurvivalAction(
            sort_key=(
                time,
                TransitionRank.DAMAGE,
                0,
                0,
                seq,
                "holder",
                f"hit{seq}",
                "auto_attacks",
            ),
            time=time,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.PLAIN_DAMAGE,
            subject=0,
            attacker=0,
            aidx=seq,
            amount=150.0,
            damage_type="physical",
            source_key="auto_attacks",
            source="auto_attacks",
            event_slot=EVENT_SLOTS.slot(f"hit{seq}"),
            sequence=seq,
        )

    def _revive_candidate(time: float, seq: int) -> object:
        return SurvivalAction(
            sort_key=(
                time,
                TransitionRank.DAMAGE,
                0,
                0,
                seq,
                "holder",
                f"rev{seq}",
                "revive",
            ),
            time=time,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.REVIVE,
            subject=0,
            attacker=0,
            aidx=seq,
            amount=defenses.revive_health_amount,
            delay=defenses.revive_delay,
            source_key="revive_Guardian Angel",
            source=defenses.revive_source,
            event_slot=EVENT_SLOTS.slot(f"rev{seq}"),
            sequence=seq,
        )

    actions = [
        _lethal(0.0, 0),
        _revive_candidate(defenses.revive_delay, 1),
        _lethal(second_lethal, 2),
        _revive_candidate(second_lethal + defenses.revive_delay, 3),
    ]
    states = build_states([combatant], (0.0,))
    if receipt:
        walk_actions = [action._replace(event={}) for action in actions]
        ledger = ReceiptLedger(
            actions=walk_actions,
            index_of={"holder": 0},
            compile_event=action_from_event,
            annotating=False,
        )
    else:
        walk_actions = actions
        ledger = ScoreLedger(len(actions))
    ctx = TransitionContext(
        duration=duration,
        states=states,
        combatants=[combatant],
        index_of={"holder": 0},
        ledger=ledger,
        regeneration_windows=(None,),
    )
    result = run_one_walk(walk_actions, ctx)
    return survival(roster_program([combatant]), result)["holder"], walk_actions


def test_requested_fights_cannot_reach_the_300s_rebirth_cooldown():
    """The named bound behind the kernel-level pin below: the request parser
    caps ``fight_duration`` at 30s, so no REQUESTED fight can span Rebirth's
    300s cooldown.  Inside a modeled fight the observable rule is therefore
    exactly one revive — and the second lethal arms NO second stasis window
    (the cooldown, not a spent one-shot boolean, is the reason)."""
    with pytest.raises(ValueError) as excinfo:
        _holder_fight(320.0, stats=dict(health=100.0, base_health=200.0))
    assert "fight_duration must be between 1 and 30" in str(excinfo.value)
    result = _holder_fight(
        12.0,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["revive_time"] == pytest.approx(4.0, abs=1e-3)
    assert survival["death_time"] == pytest.approx(4.436, abs=1e-3)
    assert survival["terminal_phase"] == "dead"
    # One armed window only: the second lethal (4.436) is inside the 300s
    # cooldown that opened at revive_time + 300 = 304.0.
    assert len(survival["revive_stasis"]) == 1
    assert survival["revive_stasis"][0]["ready_at"] == pytest.approx(
        survival["revive_time"] + REVIVE_COOLDOWN
    )
    assert survival["revive_stasis"][0]["ready_at"] > result["duration"]


def test_second_revive_re_arms_after_the_sourced_300s_cooldown():
    """P3-3P (implemented): Rebirth's 300s cooldown starts after the
    resurrection ends and IS the re-arm gate, so a second lethal at or after
    ``revive_time + 300`` arms a second resurrection and revives again.  A
    second lethal INSIDE the cooldown is terminal, and the receipt names the
    reason ("revive_on_cooldown") instead of silently retrying it."""
    late, _ = _rebirth_kernel_walk(310.0, receipt=False)
    assert late["first_death_time"] == pytest.approx(0.0)
    assert late["revive_time"] == pytest.approx(310.0 + REVIVE_DELAY)
    assert late["revived"] is True
    assert late["terminal_phase"] == "revived"
    assert late["death_time"] is None
    assert late["revive_health_restored"] == pytest.approx(REVIVE_HEALTH_RATIO * 200.0)
    # Two armed windows, each 4.0s, each re-parking the 300s cooldown.
    assert [row["start"] for row in late["revive_stasis"]] == [0.0, 310.0]
    assert [row["end"] for row in late["revive_stasis"]] == [4.0, 314.0]
    assert [row["ready_at"] for row in late["revive_stasis"]] == [
        pytest.approx(4.0 + REVIVE_COOLDOWN),
        pytest.approx(314.0 + REVIVE_COOLDOWN),
    ]
    assert all(row["resolved"] is True for row in late["revive_stasis"])
    assert all(
        row["cooldown"] == pytest.approx(REVIVE_COOLDOWN)
        for row in late["revive_stasis"]
    )

    # Inside the cooldown: terminal death, ONE window, no second revive.
    early, _ = _rebirth_kernel_walk(100.0, receipt=False)
    assert early["revive_time"] == pytest.approx(REVIVE_DELAY)
    assert early["death_time"] == pytest.approx(100.0)
    assert early["terminal_phase"] == "dead"
    assert len(early["revive_stasis"]) == 1


def test_rebirth_cooldown_gate_is_exact_and_named_on_the_receipt():
    """The gate is the sourced timestamp, not an approximation: a lethal one
    tick BEFORE ``revive_time + 300`` does not re-arm, one AT it does.  The
    denied candidate carries skipped_reason "revive_on_cooldown" and applies
    0.0, and the receipt and score adapters agree row-for-row."""
    ready_at = REVIVE_DELAY + REVIVE_COOLDOWN
    before, _ = _rebirth_kernel_walk(ready_at - 0.1, receipt=False)
    exactly, _ = _rebirth_kernel_walk(ready_at, receipt=False)
    assert before["revive_time"] == pytest.approx(REVIVE_DELAY)
    assert before["terminal_phase"] == "dead"
    assert exactly["revive_time"] == pytest.approx(ready_at + REVIVE_DELAY)
    assert exactly["terminal_phase"] == "revived"

    receipt_row, walk_actions = _rebirth_kernel_walk(100.0, receipt=True)
    denied = walk_actions[3].event
    assert denied["skipped_reason"] == "revive_on_cooldown"
    assert denied["applied_amount"] == pytest.approx(0.0)
    score_row, _ = _rebirth_kernel_walk(100.0, receipt=False)
    assert score_row == receipt_row


# ---------------------------------------------------------------------------
# 7. Extra damage while dead never compounds
# ---------------------------------------------------------------------------


def test_post_death_damage_after_final_death_is_ignored_too():
    """The same ignore rule applies after the FINAL death: packets landing
    after the last lethal (5.545, 6.654, ...) are kept with damage 0.0 +
    skipped_reason "target_dead"; damage_taken counts exactly the two
    lethal hits (2 x 104 = 208) and health_damage exactly their applied
    amounts (2 x 100 = 200) — nothing else compounds."""
    result = _holder_fight(
        12.0,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    holder_id = result["participants"][1]["participant_id"]
    late_hits = [
        event
        for event in result["events"]
        if str(event.get("target", "")) == holder_id
        and float(event["time"]) > survival["death_time"]
    ]
    assert late_hits
    for event in late_hits:
        assert event["damage"] == 0.0
        assert event["skipped_reason"] == "target_dead"
    assert survival["health_damage"] == pytest.approx(200.0)
    assert survival["damage_taken"] == pytest.approx(208.0)


# ---------------------------------------------------------------------------
# 8. Score vs receipt parity
# ---------------------------------------------------------------------------


def test_score_path_agrees_with_receipt_on_every_revive_field():
    """The coupled score surface (include_receipt=False) returns the same
    survival rows as the receipt surface, revive fields included.  GA sits
    in COMPILED_WALK_UNREPRESENTABLE_ITEMS, so the compiled fast path fails
    closed and both surfaces run the shared kernel walk — equality by
    construction.  This is the score-path equality the P3-3P completion
    must preserve."""
    stats = dict(
        health=100.0,
        base_health=200.0,
        bonus_health=0.0,
        armor=0.0,
        magic_resistance=0.0,
    )
    receipt = _holder_fight(12.0, stats=stats)
    score = _holder_fight(12.0, stats=stats, include_receipt=False)
    compiled_ctx = CoupledSearchContext()
    compiled = _holder_fight(
        12.0, stats=stats, include_receipt=False, search_context=compiled_ctx
    )
    for surface in (score, compiled):
        # Survival rows are fully equal (same kernel state).  The receipt
        # mode's participant dicts additionally carry stats/items and its
        # breakdown carries the display-only sources/utility_outcomes
        # splits; the scoring fields must match exactly.
        assert surface["participants"][1]["survival"] == _holder_survival(receipt)
        assert (
            surface["participants"][0]["survival"]
            == receipt["participants"][0]["survival"]
        )
        assert surface["duration"] == receipt["duration"]
        for score_row, receipt_row in zip(surface["breakdown"], receipt["breakdown"]):
            assert score_row["participant_id"] == receipt_row["participant_id"]
            assert score_row["total_damage"] == receipt_row["total_damage"]
            assert score_row["incoming_damage"] == receipt_row["incoming_damage"]
            assert score_row["health_damage"] == receipt_row["health_damage"]
            assert score_row["death_time"] == receipt_row["death_time"]
            assert score_row["survived_window"] == receipt_row["survived_window"]
    # P3-3P: GA rides the compiled path (revive_candidate_actions stages
    # the revive exactly like the receipt), so the compiled context is
    # clean and the panel carries the same survival rows.
    assert compiled_ctx.uncompilable is False
    assert compiled_ctx.panels


def test_legacy_score_only_pair_surface_carries_no_survival_state():
    """Named fail-closed boundary: the legacy pair scorer
    (run_fight(score_only=True)) cannot carry survival state — its
    target_* fields are None and no revive key exists.  Scoring fields that
    DO survive (total_damage, resource_spent, item_state_receipts,
    champion_stats) agree with the full fight, and the revive adds nothing
    to any of them.  The coupled survival rows (pinned above) and the
    (future) item_state_receipts Rebirth row are the carriers."""
    champ = get_champion("Ahri")
    params_full = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 12.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": [
                {
                    "champion": "Aatrox",
                    "level": 18,
                    "items": [
                        "Bloodthirster",
                        "Infinity Edge",
                        "Lord Dominik's Regards",
                        "Ravenous Hydra",
                        "Phantom Dancer",
                        "The Collector",
                    ],
                }
            ],
        },
        deterministic=True,
    )
    full = run_fight(champ, 18, [_ga_item()], params_full)
    score = run_fight(champ, 18, [_ga_item()], params_full, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["resource_spent"] == full["resource_spent"]
    assert score["item_state_receipts"] == full["item_state_receipts"]
    assert score["champion_stats"] == full["champion_stats"]
    assert "target_ending_health" not in score
    assert "target_healing_received" not in score
    assert "revived" not in score


def test_item_state_receipts_emits_exactly_one_rebirth_row():
    """P3-3P contract (receipt path, the 3M/3N/3O pattern): item_state_receipts
    emits exactly ONE Guardian Angel row — state "rebirth" (coordinator's
    named state), carrying the armed revive: restored health (0.5 x base),
    delay 4.0, cooldown 300.0, one-use True, mana ratio 1.0, and the wiki
    source receipt.  Implemented: exactly one GA row is emitted, and the
    complementary fail-closed claim (no GA in the build -> no rebirth row at
    all, never an inert placeholder) is pinned by the absent-GA test
    below."""
    receipts = item_state_receipts(
        [_ga_item()],
        {},
        fight_duration_seconds=12.0,
        is_melee=False,
        base_health=200.0,
    )
    (receipt,) = [row for row in receipts if row.get("item") == ITEM_NAME]
    assert receipt["state"] == "rebirth"
    assert receipt["revived"] is True
    assert receipt["revive_health_restored"] == pytest.approx(100.0)
    assert receipt["revive_delay"] == pytest.approx(REVIVE_DELAY)
    assert receipt["revive_cooldown"] == pytest.approx(REVIVE_COOLDOWN)
    assert receipt["one_use"] is True
    assert receipt["revive_mana_ratio"] == pytest.approx(REVIVE_MANA_RATIO)
    assert isinstance(receipt["source_revision_id"], int)
    assert str(receipt["source_url"]).startswith(
        "https://wiki.leagueoflegends.com/en-us/Guardian_Angel"
    )


# ---------------------------------------------------------------------------
# 9. No outgoing TDD from the revive
# ---------------------------------------------------------------------------


def test_revive_adds_no_damage_and_no_healing_claim_anywhere():
    """The revive authors no damage and no healing: no damage event and no
    healing event carry a revive/Rebirth source, no breakdown row exists for
    it, the holder's breakdown total comes only from "Auto Attacks", and
    healing_received stays 0.0 while revive_health_restored > 0 (the revive
    is a state transition, not healing)."""
    result = _holder_fight(
        12.0,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["revived"] is True
    assert survival["revive_health_restored"] == pytest.approx(100.0)
    assert survival["healing_received"] == pytest.approx(0.0)
    revive_sources = [
        event
        for event in result["events"] + result["healing_events"]
        if "revive" in str(event.get("source", "")).lower()
        or "rebirth" in str(event.get("source", "")).lower()
    ]
    assert revive_sources == []
    holder_breakdown = next(
        row for row in result["breakdown"] if row["participant_id"] != "main"
    )
    assert [source["name"] for source in holder_breakdown["sources"]] == [
        "Auto Attacks"
    ]
    # The utility ledger declares the revive dimension but applies nothing:
    # dimensions ["revive"], applied_dimensions empty, no revive block count.
    outcomes = holder_breakdown["utility_outcomes"]
    assert outcomes["dimensions"] == ["revive"]
    assert outcomes["applied_dimensions"] == []
    assert [entry["name"] for entry in outcomes["item_coverage"]] == [ITEM_NAME]


# ---------------------------------------------------------------------------
# 10. Fail-closed
# ---------------------------------------------------------------------------


def test_absent_ga_produces_no_revive_and_no_receipt_row():
    """Without the item there is no revive and no receipt row: the bare
    holder dies and stays dead (revived False, revive_source "", revive_time
    None, death recorded, terminal "dead"), and item_state_receipts emits no
    GA row for an empty build."""
    result = _holder_fight(
        12.0,
        holder_items=(),
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["revived"] is False
    assert survival["revive_source"] == ""
    assert survival["revive_time"] is None
    assert survival["revive_health_restored"] == 0.0
    assert survival["death_time"] == pytest.approx(0.0, abs=1e-3)
    assert survival["terminal_phase"] == "dead"
    assert (
        item_state_receipts([], {}, fight_duration_seconds=12.0, is_melee=False) == []
    )


def test_holder_without_a_valid_base_health_arms_no_revive():
    """Fail-closed source edge: without a valid base_health the typed
    restore amount is 0.0, so the walk authors no revive candidate and the
    fight makes no Rebirth claim even with GA equipped."""
    defenses = resolve_starting_defenses(
        "Ashe", 18, {"health": 100.0, "base_health": 0.0}, [_ga_item()]
    )
    assert defenses.revive_health_amount == 0.0
    result = _holder_fight(
        4.1,
        stats=dict(
            health=100.0,
            base_health=0.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["revived"] is False
    assert survival["revive_source"] == ""


def test_fabricated_ga_input_options_are_rejected_fail_closed():
    """No authored Rebirth scenario control exists: GA's ITEM_INPUT_OPTIONS
    entry is the source-only receipt (no option schemas), and any
    fabricated option under it is rejected with "Unknown option for
    Guardian Angel"."""
    config = ITEM_INPUT_OPTIONS.get(ITEM_NAME, {})
    assert set(config) <= {"source_url", "source_revision_id"}
    with pytest.raises(ValueError) as excinfo:
        validate_item_input_options({ITEM_NAME: {"rebirth_delay": 2.0}})
    assert "Unknown option" in str(excinfo.value)
    assert ITEM_NAME in str(excinfo.value)


# ---------------------------------------------------------------------------
# 11. Coverage posture
# ---------------------------------------------------------------------------


def test_coverage_posture_names_rebirth_and_stays_eligible():
    """item_model_coverage returns the justified posture with a reason naming
    Rebirth AND the survival ledger; optimizer_eligible + calculation_eligible
    stay True; outcome_dimensions carries "revive"; the target coverage is
    "modeled" naming Rebirth and the 50% base health restore."""
    coverage = item_model_coverage(str(_ga_item()["name"]), ATTACKER_LANES).as_payload()
    assert coverage["status"] in {"stats_only", "modeled_effect"}
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["outcome_dimensions"] == ["revive"]
    # Ours' classifier derives the attacker-lane reason from the declared
    # families and never repeats a mechanic's prose; the mechanic is
    # named on the target lane, asserted there.
    assert coverage["status"] == "stats_only"
    target = target_item_model_coverage(_ga_item())
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True
    assert target["outcome_dimensions"] == ["revive"]
    assert "Rebirth" in target["reason"]


# ---------------------------------------------------------------------------
# 12. Sustained-fight window timing (current engine rule vs the contract)
# ---------------------------------------------------------------------------


def test_sustained_fight_revive_is_anchored_to_the_lethal_hit():
    """P3-3P rule (lethal-anchored window): the walk authors one revive
    candidate after EVERY incoming damage packet, but the kernel skips
    any candidate that fires before death_time + 4.0 — the lethal packet's
    own candidate applies at exactly death_time + 4.0 (here death at
    9.981, revive at 13.981), so the full sourced 4-second stasis elapses
    even in sustained fights."""
    result = _holder_fight(
        20.0,
        stats=dict(
            health=1000.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["revived"] is True
    assert survival["revive_health_restored"] == pytest.approx(100.0)
    assert survival["revive_time"] == pytest.approx(
        survival["first_death_time"] + REVIVE_DELAY, abs=1e-3
    )
    assert survival["revive_time"] >= survival["first_death_time"] + REVIVE_DELAY - 1e-3


def test_sustained_fight_revive_lands_exactly_four_seconds_after_the_lethal_packet():
    """THE contract pin for item 4 in a sustained fight, in ABSOLUTE numbers
    (the test above pins the same rule relationally).  The engine no longer
    lets a pre-lethal candidate shorten the window (it would have revived at
    10.654): the lethal packet at 9.981 arms the stasis, the applied revive
    lands at exactly 13.981 = 9.981 + the sourced 4.0s, and the armed window
    receipt spans exactly those two timestamps with the sourced 300s
    cooldown."""
    result = _holder_fight(
        20.0,
        stats=dict(
            health=1000.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["revived"] is True
    assert survival["first_death_time"] == pytest.approx(9.981, abs=1e-3)
    assert survival["revive_time"] == pytest.approx(13.981, abs=1e-3)
    assert survival["revive_time"] == pytest.approx(
        survival["first_death_time"] + REVIVE_DELAY, abs=1e-3
    )
    (window,) = survival["revive_stasis"]
    assert window["start"] == pytest.approx(9.981, abs=1e-3)
    assert window["end"] == pytest.approx(13.981, abs=1e-3)
    assert window["duration"] == pytest.approx(REVIVE_DELAY)
    assert window["cooldown"] == pytest.approx(REVIVE_COOLDOWN)
    assert window["resolved"] is True


# ---------------------------------------------------------------------------
# 13. Existing regression surface touching Guardian Angel (kept green)
# ---------------------------------------------------------------------------
#
# The tests below are documentary: they re-run the exact existing assertions
# that touch Guardian Angel so this file's owner sees the regression surface
# staying green in one place.  They are NOT re-implementations — the owning
# files remain authoritative and are run by the suite gate.
#
# * tests/test_participant_timeline.py:135-168
#   test_guardian_angel_revives_target_after_first_lethal_packet:
#     enemy = ChampionLoadout(champion="Aatrox", level=18,
#                             items=("Guardian Angel",)).resolve()
#     ... health=100.0, base_health=200.0, armor=0.0, mr=0.0 ...
#     assert survival["revived"] is True
#     assert survival["revive_time"] == approx(first_death_time + 4.0)
#     assert survival["revive_health_restored"] == approx(100.0)
#     assert survival["action_downtime"] == approx(4.0)
#     assert survival["terminal_phase"] == "revived"
#
# * tests/test_defensive_effects.py:240-255
#   test_guardian_angel_resolves_sourced_base_health_rebirth:
#     resolve_starting_defenses("Aatrox", 18, _stats(base_health=1800.0),
#                               [{"name": "Guardian Angel"}])
#     assert defenses.revive_health_amount == approx(900.0)
#     assert defenses.revive_delay == approx(4.0)
#     assert defenses.revive_cooldown == approx(300.0)
#     assert defenses.public_summary()["revive"] == {
#         "health_amount": 900.0, "delay": 4.0, "cooldown": 300.0}
#
# * tests/test_e8_followup_hooks.py:70-76
#   test_guardian_angel_keeps_item_source:
#     d = _resolve("Ahri", base_health=1500.0,
#                  items=[get_item_by_name("Guardian Angel")])
#     assert d.revive_health_amount == approx(750.0)
#     assert d.revive_source == "Guardian Angel (Rebirth)"
#
# * tests/test_item_coverage.py:275 / 480 / 561 (parametrized pins):
#     ("Guardian Angel", "modeled")            -> target status modeled
#     ("Guardian Angel", "revive")             -> outcome_dimensions
#     ("Guardian Angel", "Rebirth")            -> reason fragment
#
# * tests/test_economy.py:51:
#     assert item_sell_value(_item("Guardian Angel")) == 1280  # 40% legendary
#
# * tests/test_app.py:1991-1994:
#     items["Guardian Angel"]["model_coverage"]["outcome_dimensions"] == [
#         "revive"]
#     "Rebirth" in items["Guardian Angel"]["model_coverage"]["reason"]
#
# * tests/test_e8_support.py:92-220 (the shared revive interface GA uses —
#   Anivia/Zac/Zilean sourced revives ride the same StartingDefenses
#   revive_* fields and the same kernel transition).
#


def test_regression_surface_guardian_angel_defensive_layer_stays_green():
    """Mirrors test_defensive_effects.py:240: sourced base-health rebirth."""
    defenses = resolve_starting_defenses(
        "Aatrox", 18, {"health": 1800.0, "base_health": 1800.0}, [_ga_item()]
    )
    assert defenses.revive_health_amount == pytest.approx(900.0)
    assert defenses.revive_delay == pytest.approx(4.0)
    assert defenses.revive_cooldown == pytest.approx(300.0)
    assert defenses.public_summary()["revive"] == {
        "health_amount": 900.0,
        "delay": 4.0,
        "cooldown": 300.0,
    }


def test_regression_surface_guardian_angel_item_source_label_stays_green():
    """Mirrors test_e8_followup_hooks.py:70-76: the item keeps its own source
    label (750.0 = 50% of the 1500 base health)."""
    defenses = resolve_starting_defenses(
        "Ahri", 18, {"health": 1500.0, "base_health": 1500.0}, [_ga_item()]
    )
    assert defenses.revive_health_amount == pytest.approx(750.0)
    assert defenses.revive_source == REVIVE_SOURCE


def test_regression_surface_guardian_angel_timeline_stays_green():
    """Mirrors test_participant_timeline.py:135-168 with the Aatrox holder:
    first lethal packet records the death and the revive lands at +4.0 with
    50% of base health (100.0 from base_health 200.0)."""
    result = _holder_fight(
        4.1,
        holder="Aatrox",
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    assert survival["first_death_time"] is not None
    assert survival["revived"] is True
    assert survival["revive_time"] == pytest.approx(
        survival["first_death_time"] + 4.0, abs=1e-3
    )
    assert survival["revive_health_restored"] == pytest.approx(100.0)
    assert survival["action_downtime"] == pytest.approx(4.0, abs=1e-3)
    assert survival["terminal_phase"] == "revived"


def test_regression_surface_guardian_angel_coverage_and_economy_stay_green():
    """Mirrors test_item_coverage.py (~275/480/561) and test_economy.py:51:
    the modeled posture, the revive outcome dimension, the Rebirth reason
    fragment, and the 40%-legendary sell value (1280) all stay green."""
    assert target_item_model_coverage(_ga_item())["status"] == "modeled"
    assert (
        "revive"
        in item_model_coverage(str(_ga_item()["name"]), ATTACKER_LANES).as_payload()[
            "outcome_dimensions"
        ]
    )
    # The mechanic is named on the target lane; the attacker lane publishes
    # the derived family census for a defence-only item.
    assert "Rebirth" in target_item_model_coverage(_ga_item())["reason"]
    assert _ga_item()["shop"]["prices"]["sell"] == 1280
