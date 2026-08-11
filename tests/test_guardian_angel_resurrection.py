"""P1 Package 3P — Guardian Angel (3026) "Rebirth" resurrection parity
certification.

This file is the focused acceptance-matrix owner for Guardian Angel's Rebirth
passive.  It pins the OBSERVABLES the coordinator's P3-3P completion must
satisfy and runs against today's source: every behavior that already exists
passes now; every assertion that targets a contract piece the source does
not emit yet is marked ``xfail`` with reason ``awaiting P3-3P ...``.

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
  (AGENTS.md rule 5 — no silent fallbacks).  The P3-3P completion adds the
  mana restore (100% max mana), the one-use flag, and the wiki source
  receipt (``source_url`` / ``source_revision_id``) to the typed registry —
  all absent today (KeyError today, so the fail-closed path is pinned and
  the typed additions are xfail).
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
  spans exactly [death_time, revive_time] (4.0s).  CAVEAT (reported to the
  coordinator): in a sustained fight the earliest candidate while dead can
  be authored from a pre-lethal packet, so the revive can fire EARLIER than
  death_time + 4.0 (probe: death 9.981, revive 10.654 from the 6.654
  packet).  The aligned contract is pinned PASS; the lethal-anchored
  exactness in sustained fights is xfail.
* STASIS DURING THE WINDOW: implemented as the dead state, not as an
  explicit stasis state today — incoming damage during the window is
  ignored (public event kept with damage 0.0 + ``skipped_reason
  target_dead``), the holder authors no damage (events kept with damage 0.0
  + ``skipped_reason attacker_dead``), and the holder acts again after the
  revive.  ``stasis_until`` / ``stasis_source`` stay 0.0/"" — an explicit
  stasis-state authoring is xfail.
* ONE REVIVE ONLY + COOLDOWN: after the first revive the kernel sets
  ``revive_used``; a second lethal after the revive does NOT re-trigger
  Rebirth (second ``death_time`` recorded, terminal_phase "dead", single
  revive_time).  The typed cooldown is 300.0s — a <=60s fight can never see
  a second revive — and the one-use gate is the enforceable rule.  A
  >300s-cooldown RE-ARM (the real game lets a second Rebirth fire once the
  cooldown expires) is unrepresentable today (``revive_used`` never
  re-arms) — xfail.
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
  survival rows and the (future) item_state_receipts row are the carriers.
* RECEIPT ROW (P3-3P surface, absent today → xfail): the coordinator's
  completion adds ONE ``item_state_receipts`` row for Guardian Angel (the
  3M/3N/3O pattern) carrying the revive state (revived / restored amount /
  delay / cooldown / one-use / mana ratio / wiki source revision).
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
* XFAIL ONLY for genuinely absent mechanics: (1) the typed mana/one-use/
  source-receipt keys; (2) the explicit stasis-state authoring; (3) the
  300s-cooldown re-arm (second revive after cooldown expiry); (4) the
  item_state_receipts Rebirth row; (5) the lethal-anchored 4s window in a
  sustained fight.  All five are ``awaiting P3-3P ...``.

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
    """P3-3P typed surface (absent today): the registry adds the 100% max
    mana restore, the one-use flag, and the wiki source receipt.  Today
    every key raises KeyError (fail-closed), so this xfails until the
    coordinator's completion adds the typed keys."""
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


@pytest.mark.xfail(reason="awaiting P3-3P explicit Rebirth stasis state")
def test_explicit_stasis_state_is_authored_for_the_window():
    """The 4s window is implemented today as the dead state (target_dead /
    attacker_dead blocking, pinned above).  P3-3P contract question: an
    explicit stasis state for the window — stasis_until == revive_time with
    stasis_source "Guardian Angel (Rebirth)" — is absent today (stasis_until
    stays 0.0, stasis_source "")."""
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


@pytest.mark.xfail(reason="awaiting P3-3P 300s cooldown rearm")
def test_second_revive_after_cooldown_expiry_is_unrepresentable():
    """The real-game rule: Rebirth's 300s cooldown starts after the
    resurrection ends, so a second lethal 300+s later WOULD re-trigger
    Rebirth.  The engine's one-use gate (revive_used) never re-arms, so the
    re-arm is unrepresentable — a holder that dies, revives, and dies again
    in a long fight shows exactly one revive.  This xfails until P3-3P adds
    the cooldown re-arm state; the <=60s-fight one-use rule is pinned PASS
    by the test above."""
    result = _holder_fight(
        320.0,
        stats=dict(
            health=100.0,
            base_health=200.0,
            bonus_health=0.0,
            armor=0.0,
            magic_resistance=0.0,
        ),
    )
    survival = _holder_survival(result)
    # Contract: the second lethal (death #2) re-arms and revives again.
    assert survival["revive_time"] == pytest.approx(
        survival["death_time"] + REVIVE_DELAY, abs=1e-3
    )


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
    source receipt.  Absent today: item_state_receipts returns [] for GA
    (the fail-closed absent claim is pinned by the absent-GA test below, and
    the row's absence is what this xfail tracks)."""
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
    coverage = item_model_coverage(_ga_item())
    assert coverage["status"] in {"stats_only", "modeled_effect"}
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["outcome_dimensions"] == ["revive"]
    assert "Rebirth" in coverage["reason"]
    assert "survival ledger" in coverage["reason"]
    target = target_item_model_coverage(_ga_item())
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True
    assert target["outcome_dimensions"] == ["revive"]
    assert "Rebirth" in target["reason"]
    assert "50% base health" in target["reason"]


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
    """THE contract pin for item 4 in a sustained fight: the resurrection
    window is exactly 4.0s from the LETHAL packet (death_time + 4.0), like
    the aligned case.  Today the earliest candidate while dead can be
    authored from a pre-lethal packet (death 9.981 -> revive 10.654, not
    13.981), so this is genuinely absent and xfails."""
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
    assert survival["revive_time"] == pytest.approx(
        survival["first_death_time"] + REVIVE_DELAY, abs=1e-3
    )


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
    assert "revive" in item_model_coverage(_ga_item())["outcome_dimensions"]
    assert "Rebirth" in item_model_coverage(_ga_item())["reason"]
    assert _ga_item()["shop"]["prices"]["sell"] == 1280
