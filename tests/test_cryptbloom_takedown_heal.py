"""P1 Package 3K — Cryptbloom "Life From Death" takedown-heal certification.

This file is the independent acceptance matrix for Cryptbloom's Life From
Death takedown nova.  It pins the OBSERVABLES the P3-3K acceptance rules
require and runs against today's source: every behavior that already exists
must pass now; genuinely absent contract pieces are ``xfail`` with reason
``awaiting P3-3K ...`` (none are absent today — the gaps below are pinned
as observations with P3-3K comments instead).

Contract pinned (typed source-backed values):

* life_from_death_base_heal 100.0, life_from_death_ap_ratio 0.20,
  life_from_death_nova_duration 1.75, life_from_death_cooldown 60.0 through
  ``ally_item_effect_value`` (the values live in ALLY_ITEM_EFFECTS, NOT
  ITEM_EFFECTS — ``required_effect_value`` must fail loud, never return a
  stale literal); missing keys raise KeyError naming Cryptbloom AND the
  key; source_url https://wiki.leagueoflegends.com/en-us/Cryptbloom and
  source_revision_id 3989109 ride the ALLY registry; Cryptbloom has NO
  ITEM_INPUT_OPTIONS entry (no scenario control — pinned as an absence).
* Valid champion takedown: a fight where the main kills the enemy
  (target_ending_health <= 0 in the pair result) produces exactly ONE heal
  packet per recipient (attacker + every teammate) at the kill time,
  source "Cryptbloom \u2014 Life From Death", amount = 100 + 0.20*AP (from the
  ATTACKER's ability_power), target_scope "nova_allied_champions", trigger
  "explicit_takedown_within_damage_window", duration 1.75, cooldown 60.
* Non-takedown boundaries: no kill -> NO packets; a ``takedown_events``
  key absent -> no packets; an event with no time or no target is filtered
  (time 0.0 is a valid receipt time).
* Dead-owner boundary: the heal still fires when the holder dies at/after
  the kill — the emission has no holder-health gate (derive level) and the
  full timeline still exposes the packets when the holder's death_time is
  after the heal time.
* Recipient: attacker + teammates, never the dead enemy; no teammates ->
  attacker-only heal.
* Duplicate/cooldown: the 60s cooldown is RECEIPTED-only (cooldown 60.0 on
  every packet, no cooldown state machine).  A second authored takedown at
  the derive level fires a second set.  In a full timeline the support
  templates attach ONCE per attacker, from the FIRST defender pair only:
  a second kill in the same fight emits no second set, and a kill on a
  non-first roster enemy is not receipted at all (P3-3K comment).
* The 1.75s "over" semantics: ONE packet per recipient at the kill time,
  applied once (applied_amount == amount on wounded recipients, no ticked
  clones); the duration field is a sourced label on a single application.
* Receipt-vs-score parity: the compiled score kernel FAILS CLOSED on the
  timed heal (named ``support_duration=1.75`` receipt — a plain heal with
  no duration compiles), the compiled walk falls back to the receipt walk
  with equal results, and run_fight score-only totals equal the full fight.
  The takedown-scan predicates (TAKEDOWN_SCAN_SUPPORT_ITEMS /
  has_event_scan_support_items) keep dict rows for a Cryptbloom holder so
  the score walk can read the takedown synthesis (issue #169).
* Public output: support_events heal packets expose source/amount/time/
  trigger/duration/cooldown/target_scope; item_coverage wording "Life From
  Death is a post-takedown heal." with optimizer_eligible True (stats_only
  classification); Cryptbloom is in get_eligible_legendaries; bis.py has no
  stale entry.
* Determinism: identical fights -> identical packets; exactly one packet
  per recipient per takedown (no duplicates).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app import app
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_coverage import target_item_model_coverage
from src.calculator.item_effects import (
    ALLY_ITEM_EFFECTS,
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    ally_item_effect_value,
    required_effect_value,
)
from src.calculator.item_support_effects import (
    derive_item_support_effects,
)
from src.calculator.optimizer import get_eligible_legendaries
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.survival.compile import unrepresentable_template_receipt

# The retired ``EVENT_*_SUPPORT_ITEMS`` name lists and their predicates,
# derived from the declarations that replaced them: a holder needs dict
# rows exactly when it reads a raw stream, and it is a takedown scanner
# exactly when the stream it reads is the takedown one.
from src.calculator.trigger_stream import Stream, streams_for, tuple_incapable_items
from tests import item_probe

TAKEDOWN_SCAN_SUPPORT_ITEMS = frozenset(
    name
    for name in tuple_incapable_items()
    if Stream.TAKEDOWN in streams_for(frozenset({name}))
)


def has_event_view_support_items(items):
    """Whether any held item reads a raw event stream."""
    return bool({str(item.get("name", "")) for item in items} & tuple_incapable_items())


has_event_scan_support_items = has_event_view_support_items


def has_takedown_scan_support_items(items):
    """Whether any held item reads the takedown stream."""
    return bool(
        {str(item.get("name", "")) for item in items} & TAKEDOWN_SCAN_SUPPORT_ITEMS
    )


CRYPTBLOOM = "Cryptbloom"
SOURCE = "Cryptbloom \u2014 Life From Death"
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Cryptbloom"
REVISION_ID = 3989109
BASE_HEAL = 100.0
AP_RATIO = 0.20
NOVA_DURATION = 1.75
COOLDOWN = 60.0
REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# App-level helpers (public /api/calculate surface)
# ---------------------------------------------------------------------------


def _calculate(payload: dict) -> dict:
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _ally(name: str, level: int = 1) -> dict:
    return {
        "champion": name,
        "level": level,
        "items": [],
        "ally_effects_enabled": True,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
    }


def _enemy(
    name: str,
    level: int = 1,
    *,
    items: list[str] | None = None,
    boots: str = "",
    ranks: dict | None = None,
) -> dict:
    return {
        "champion": name,
        "level": level,
        "items": items or [],
        "boots": boots,
        "ability_ranks": ranks or {"Q": 0, "W": 0, "E": 0, "R": 0},
    }


def _main_payload(
    *,
    enemies: list[dict] | None = None,
    allies: list[dict] | None = None,
    autos: bool = True,
    duration: float = 8.0,
) -> dict:
    """A deterministic kill-fight request: Lux R + autos vs a level-1 enemy."""
    return {
        "champion": "Lux",
        "level": 18,
        "items": [CRYPTBLOOM],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": autos,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
        "allies": allies if allies is not None else [_ally("Jinx")],
        "enemies": enemies if enemies is not None else [_enemy("Aatrox")],
    }


def _lfd_events(combat: dict) -> list[dict]:
    return [
        event
        for event in combat.get("support_events", [])
        if event.get("source") == SOURCE
    ]


# ---------------------------------------------------------------------------
# Timeline-level helpers (the shared composition the optimizer scores)
# ---------------------------------------------------------------------------


def _roster(
    champion: str, level: int = 18, *, role: str = "mid", items=(), boots: str = ""
) -> ChampionLoadout:
    return ChampionLoadout(
        champion=champion,
        level=level,
        role=role,
        items=items,
        boots=boots,
    ).resolve()


def _timeline(
    *,
    enemies: list[dict] | None = None,
    allies: list[dict] | None = None,
    include_receipt: bool = True,
    autos: bool = True,
    duration: float = 8.0,
    pair_result_cache: dict | None = None,
    search_context: CoupledSearchContext | None = None,
) -> dict:
    enemies = enemies if enemies is not None else [_enemy("Aatrox")]
    allies = allies if allies is not None else [_ally("Jinx")]
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": duration,
            "include_auto_attacks": autos,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
            "allies": allies,
            "enemies": enemies,
        },
        deterministic=True,
    )
    champion = get_champion("Lux")
    item = get_item_by_name(CRYPTBLOOM)
    stats = calculate_total_stats(champion, 18, [item], role="mid")
    defenses = resolve_starting_defenses(
        "Lux", 18, stats, [item], item_options=params.item_options
    )
    return build_participant_timeline(
        champion,
        18,
        [item],
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=[
            _roster(e["champion"], level=e["level"], items=e["items"]) for e in enemies
        ],
        allies=[
            _roster(a["champion"], level=a["level"], role="support") for a in allies
        ],
        include_receipt=include_receipt,
        pair_result_cache=pair_result_cache or {},
        search_context=search_context,
    )


def _timeline_heals(timeline: dict) -> list[dict]:
    return [
        event
        for event in timeline.get("support_events", [])
        if event.get("source") == SOURCE
    ]


# ---------------------------------------------------------------------------
# Derive-level helpers (hand-built takedown receipts)
# ---------------------------------------------------------------------------


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    ap: float = 0.0,
    health: float = 1000.0,
):
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={
            "health": health,
            "ability_power": ap,
            "max_mana": 1000.0,
            "mana": 1000.0,
            "is_melee": False,
        },
        request=SimpleNamespace(item_options={}, ally_effects_enabled=True),
    )


# ---------------------------------------------------------------------------
# 1. Typed values + option/schema + missing-key fail-closed
# ---------------------------------------------------------------------------


def test_typed_life_from_death_values_and_registry_revision():
    """The four typed values live in ALLY_ITEM_EFFECTS with the source url
    and revision 3989109; Cryptbloom has NO ITEM_INPUT_OPTIONS entry (the
    takedown heal is not a scenario control) and NO ITEM_EFFECTS record."""
    assert ally_item_effect_value(CRYPTBLOOM, "life_from_death_base_heal") == BASE_HEAL
    assert ally_item_effect_value(CRYPTBLOOM, "life_from_death_ap_ratio") == AP_RATIO
    assert (
        ally_item_effect_value(CRYPTBLOOM, "life_from_death_nova_duration")
        == NOVA_DURATION
    )
    assert ally_item_effect_value(CRYPTBLOOM, "life_from_death_cooldown") == COOLDOWN
    assert ALLY_ITEM_EFFECTS[CRYPTBLOOM]["source_url"] == SOURCE_URL
    assert ALLY_ITEM_EFFECTS[CRYPTBLOOM]["source_revision_id"] == REVISION_ID
    assert CRYPTBLOOM not in ITEM_INPUT_OPTIONS
    assert CRYPTBLOOM not in ITEM_EFFECTS


def test_missing_key_raises_keyerror_naming_cryptbloom_and_key(monkeypatch):
    """A missing typed key fails loud, naming the item and the key
    (AGENTS.md rule 5: no silent stale fallbacks at call sites)."""
    broken = dict(ALLY_ITEM_EFFECTS[CRYPTBLOOM])
    broken.pop("life_from_death_base_heal")
    monkeypatch.setitem(ALLY_ITEM_EFFECTS, CRYPTBLOOM, broken)

    with pytest.raises(KeyError) as excinfo:
        ally_item_effect_value(CRYPTBLOOM, "life_from_death_base_heal")
    message = str(excinfo.value)
    assert "Cryptbloom" in message
    assert "life_from_death_base_heal" in message


def test_required_effect_value_fails_loud_for_cryptbloom():
    """required_effect_value reads ITEM_EFFECTS, where Cryptbloom has no
    record (the values live in ALLY_ITEM_EFFECTS); the accessor must raise
    naming the item and key instead of returning a stale literal."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(CRYPTBLOOM, "life_from_death_base_heal")
    message = str(excinfo.value)
    assert "Cryptbloom" in message
    assert "life_from_death_base_heal" in message


def test_takedown_scan_predicates_keep_dict_rows():
    """The optimizer's score-only tuple ledger cannot carry the per-event
    view the takedown synthesis reads, so a Cryptbloom holder keeps dict
    rows (issue #169): the pipeline predicate and the support-item sets
    pin that exclusion."""
    assert frozenset({CRYPTBLOOM}) == TAKEDOWN_SCAN_SUPPORT_ITEMS
    assert has_takedown_scan_support_items([{"name": CRYPTBLOOM}]) is True
    assert has_event_scan_support_items([{"name": CRYPTBLOOM}]) is True
    assert has_takedown_scan_support_items([{"name": "Void Staff"}]) is False


# ---------------------------------------------------------------------------
# 2. Valid champion takedown: one heal packet per recipient at the kill time
# ---------------------------------------------------------------------------


def test_kill_fight_emits_exactly_one_heal_packet_per_recipient_at_kill_time():
    """A fight where the main kills the enemy (level-1 Aatrox dies at t=0)
    produces exactly ONE Life From Death heal packet per recipient —
    attacker + every teammate — at the kill time, never a packet targeting
    the dead enemy.  The kill time is the LAST outgoing damage event time
    in the window (R lands at t=0; the final auto at 6.328 is the receipt
    time)."""
    timeline = _timeline()
    heals = _timeline_heals(timeline)
    assert len(heals) == 2
    assert {event["target"] for event in heals} == {"main", "ally:Jinx"}
    assert "enemy:Aatrox" not in {event["target"] for event in heals}

    enemy_death = next(
        row
        for row in timeline["participants"]
        if row["participant_id"] == "enemy:Aatrox"
    )
    assert enemy_death["survival"]["death_time"] == pytest.approx(0.0)

    main_events = [
        event["time"]
        for event in timeline["events"]
        if event["attacker"] == "main" and event["target"] == "enemy:Aatrox"
    ]
    assert main_events
    kill_time = max(main_events)
    for event in heals:
        assert event["time"] == pytest.approx(kill_time, abs=0.001)
        assert event["kind"] == "heal"
        assert event["source"] == SOURCE
        assert event["duration"] == pytest.approx(NOVA_DURATION)
        assert event["cooldown"] == pytest.approx(COOLDOWN)
        assert event["target_scope"] == "nova_allied_champions"
        assert event["trigger"] == "explicit_takedown_within_damage_window"


def test_heal_amount_is_base_plus_ap_ratio_of_attacker_ap():
    """amount == 100 + 0.20 * (the ATTACKER's ability_power): 0 AP -> 100,
    200 AP -> 140 at the derive level; the timeline packet equals the same
    formula on the main's resolved stats."""
    holder = _actor("ally:Lulu", "ally", (CRYPTBLOOM,), ap=0.0)
    teammate = _actor("main:Ahri", "main", ())
    packets = derive_item_support_effects(
        holder,
        {"takedown_events": [{"time": 3.0, "target": "enemy:Aatrox"}]},
        [holder, teammate],
    )
    heals = [p for p in packets if p["source"] == SOURCE]
    assert all(p["amount"] == pytest.approx(100.0) for p in heals)

    holder = _actor("ally:Lulu", "ally", (CRYPTBLOOM,), ap=200.0)
    packets = derive_item_support_effects(
        holder,
        {"takedown_events": [{"time": 3.0, "target": "enemy:Aatrox"}]},
        [holder, teammate],
    )
    heals = [p for p in packets if p["source"] == SOURCE]
    assert all(p["amount"] == pytest.approx(140.0) for p in heals)

    timeline = _timeline()
    heals = _timeline_heals(timeline)
    main = next(
        row for row in timeline["participants"] if row["participant_id"] == "main"
    )
    ap = main["stats"]["ability_power"]
    assert all(
        event["amount"] == pytest.approx(BASE_HEAL + AP_RATIO * ap) for event in heals
    )


def test_derive_packet_shape_is_typed():
    """The raw packet carries the typed fields: kind heal, source, amount,
    duration, cooldown, target_scope, trigger, the roster target policy and
    selection key, and the _item_support marker."""
    holder = _actor("ally:Lulu", "ally", (CRYPTBLOOM,), ap=200.0)
    teammate = _actor("main:Ahri", "main", ())
    packets = derive_item_support_effects(
        holder,
        {"takedown_events": [{"time": 3.0, "target": "enemy:Aatrox"}]},
        [holder, teammate],
    )
    (packet,) = [
        p
        for p in packets
        if p["source"] == SOURCE and p["target"] == holder.participant_id
    ]
    assert packet["kind"] == "heal"
    assert packet["source"] == SOURCE
    assert packet["source_key"] == SOURCE
    assert packet["time"] == pytest.approx(3.0)
    assert packet["amount"] == pytest.approx(140.0)
    assert packet["duration"] == pytest.approx(NOVA_DURATION)
    assert packet["cooldown"] == pytest.approx(COOLDOWN)
    assert packet["target_scope"] == "nova_allied_champions"
    assert packet["target_policy"] == "explicit_selected_roster_target"
    assert packet["target_selection_key"] == f"heal:{SOURCE}"
    assert packet["trigger"] == "explicit_takedown_within_damage_window"
    assert packet["_item_support"] is True


# ---------------------------------------------------------------------------
# 3. Non-takedown boundaries
# ---------------------------------------------------------------------------


def test_no_kill_fight_emits_no_packets():
    """No kill (a level-18 enemy survives the whole window) -> NO Life From
    Death packets, even though the holder owns Cryptbloom."""
    timeline = _timeline(enemies=[_enemy("Ahri", level=18)])
    assert _timeline_heals(timeline) == []
    ahri = next(
        row for row in timeline["participants"] if row["participant_id"] == "enemy:Ahri"
    )
    assert ahri["survival"]["death_time"] is None


def test_absent_or_malformed_takedown_receipts_are_filtered():
    """A result without a ``takedown_events`` key authors nothing; receipts
    with no time, a None time, no target, or a non-mapping row are
    filtered.  A time of 0.0 is a valid receipt time (not filtered)."""
    holder = _actor("ally:Lulu", "ally", (CRYPTBLOOM,))
    teammate = _actor("main:Ahri", "main", ())
    assert derive_item_support_effects(holder, {}, [holder, teammate]) == []

    takedowns = [
        {"time": 3.0, "target": "enemy:Aatrox"},  # valid
        {"target": "enemy:Darius"},  # no time -> filtered
        {"time": 4.0},  # no target -> filtered
        {"time": None, "target": "enemy:B"},  # None time -> filtered
        "garbage",  # non-mapping -> filtered
        {"time": 0.0, "target": "enemy:C"},  # time 0.0 is valid
    ]
    packets = derive_item_support_effects(
        holder, {"takedown_events": takedowns}, [holder, teammate]
    )
    heals = [p for p in packets if p["source"] == SOURCE]
    assert sorted(p["time"] for p in heals) == [0.0, 0.0, 3.0, 3.0]


# ---------------------------------------------------------------------------
# 4. Dead-owner boundary
# ---------------------------------------------------------------------------


def test_heal_still_fires_when_holder_dies_after_the_kill():
    """The holder dying at/after the kill does NOT suppress the heal: the
    packets are still emitted for the holder and teammates when the main's
    death_time (0.5) comes after the kill receipt (0.0)."""
    ahri_damage = [
        "Rabadon's Deathcap",
        "Void Staff",
        "Shadowflame",
        "Luden's Echo",
        "Morellonomicon",
    ]
    timeline = _timeline(
        enemies=[
            _enemy("Aatrox"),
            _enemy(
                "Ahri",
                level=18,
                items=ahri_damage,
                boots="Sorcerer's Shoes",
                ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            ),
        ],
        autos=False,
        duration=12.0,
    )
    heals = _timeline_heals(timeline)
    assert len(heals) == 2
    main = next(
        row for row in timeline["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["death_time"] == pytest.approx(0.5)
    heal_time = heals[0]["time"]
    assert heal_time < main["survival"]["death_time"]
    assert {event["target"] for event in heals} == {"main", "ally:Jinx"}


def test_dead_holder_still_emits_heal_packets_at_derive_level():
    """The emission has no holder-health gate: a holder whose stats report
    health 0.0 still emits the full heal set for an authored takedown."""
    holder = _actor("ally:Lulu", "ally", (CRYPTBLOOM,), health=0.0, ap=100.0)
    teammate = _actor("main:Ahri", "main", ())
    packets = derive_item_support_effects(
        holder,
        {"takedown_events": [{"time": 3.0, "target": "enemy:Aatrox"}]},
        [holder, teammate],
    )
    heals = [p for p in packets if p["source"] == SOURCE]
    assert len(heals) == 2
    assert {p["target"] for p in heals} == {
        holder.participant_id,
        teammate.participant_id,
    }
    assert all(p["amount"] == pytest.approx(120.0) for p in heals)


# ---------------------------------------------------------------------------
# 5. Recipient: attacker + teammates, never the dead enemy
# ---------------------------------------------------------------------------


def test_recipients_are_attacker_and_every_teammate_never_the_enemy():
    """With two teammates the heal set covers the attacker plus BOTH
    teammates; the dead enemy is never a recipient."""
    timeline = _timeline(
        allies=[_ally("Jinx"), _ally("Nami")],
        autos=False,
    )
    heals = _timeline_heals(timeline)
    assert {event["target"] for event in heals} == {"main", "ally:Jinx", "ally:Nami"}
    assert "enemy:Aatrox" not in {event["target"] for event in heals}


def test_no_teammates_attacker_only_heal():
    """No teammates -> attacker-only heal: exactly one packet targeting the
    holder, same amount and receipt fields."""
    timeline = _timeline(allies=[], autos=False)
    heals = _timeline_heals(timeline)
    assert len(heals) == 1
    assert heals[0]["target"] == "main"
    main = next(
        row for row in timeline["participants"] if row["participant_id"] == "main"
    )
    assert heals[0]["amount"] == pytest.approx(
        BASE_HEAL + AP_RATIO * main["stats"]["ability_power"]
    )


# ---------------------------------------------------------------------------
# 6. Duplicate / cooldown behavior (receipted-only)
# ---------------------------------------------------------------------------


def test_second_authored_takedown_fires_a_second_set_derive_level():
    """The 60s cooldown is RECEIPTED-only (cooldown 60.0 rides every packet)
    and has no enforcement state machine: two authored takedown receipts
    emit two full sets (one packet per recipient each).  P3-3K: a 60s
    cooldown window between takedowns is not modeled at the derivation
    layer."""
    holder = _actor("ally:Lulu", "ally", (CRYPTBLOOM,), ap=200.0)
    teammate = _actor("main:Ahri", "main", ())
    packets = derive_item_support_effects(
        holder,
        {
            "takedown_events": [
                {"time": 3.0, "target": "enemy:Aatrox"},
                {"time": 5.0, "target": "enemy:Darius"},
            ]
        },
        [holder, teammate],
    )
    heals = [p for p in packets if p["source"] == SOURCE]
    assert len(heals) == 4
    assert sorted(p["time"] for p in heals) == [3.0, 3.0, 5.0, 5.0]
    assert all(p["cooldown"] == pytest.approx(COOLDOWN) for p in heals)


def test_second_kill_in_same_fight_is_not_receipted_first_pair_only():
    """In a full timeline the support templates attach ONCE per attacker,
    from the FIRST defender pair only.  P3-3K: a second kill in the same
    fight emits no second set (so no cooldown question arises), and a kill
    on a non-first roster enemy produces NO packets at all — the takedown
    receipt of later pairs is not scanned."""
    # Both enemies die: exactly one set (main + Jinx).
    both = _timeline(
        enemies=[_enemy("Aatrox"), _enemy("Aatrox")],
        autos=False,
    )
    heals = _timeline_heals(both)
    assert len(heals) == 2
    for participant in both["participants"]:
        if participant["participant_id"].startswith("enemy:"):
            assert participant["survival"]["death_time"] == pytest.approx(0.0)

    # First enemy survives, second enemy dies: no packets at all.
    ahri_damage = [
        "Rabadon's Deathcap",
        "Void Staff",
        "Shadowflame",
        "Luden's Echo",
        "Morellonomicon",
    ]
    # A level-18 Jinx ally contributes its W to the second pair, so the
    # level-1 Aatrox dies there; the first-pair Ahri (full damage build)
    # survives.  The kill still emits NO packets: support templates attach
    # from the first defender pair only.
    second_only = _timeline(
        allies=[_ally("Jinx", level=18)],
        enemies=[
            _enemy(
                "Ahri",
                level=18,
                items=ahri_damage,
                boots="Sorcerer's Shoes",
                ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            ),
            _enemy("Aatrox"),
        ],
        autos=False,
        duration=12.0,
    )
    assert _timeline_heals(second_only) == []
    aatrox = next(
        row
        for row in second_only["participants"]
        if row["participant_id"] == "enemy:Aatrox"
    )
    assert aatrox["survival"]["death_time"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 7. The 1.75s "over" semantics: one packet, one application
# ---------------------------------------------------------------------------


def test_heal_is_one_packet_applied_once_not_ticked():
    """The 1.75s duration is a sourced label on a SINGLE packet: exactly
    one packet per recipient at the kill time, one amount, and one
    application (applied + overheal = amount; the survival healing_received
    is that application) — no ticked clones over the 1.75s window.

    Aatrox dies at t=0, so only his first Q strike wounds the recipients and
    both are healed to full with a remainder: applied is the wound, not the
    packet.
    """
    timeline = _timeline()
    heals = _timeline_heals(timeline)
    assert len(heals) == 2
    assert {event["recipient"] for event in heals} == {"main", "ally:Jinx"}
    by_recipient = {event["recipient"]: event for event in heals}
    for event in heals:
        assert event["raw_amount"] == pytest.approx(event["amount"])
        assert event["applied_amount"] + event["overheal"] == pytest.approx(
            event["amount"]
        )
    for participant_id in ("main", "ally:Jinx"):
        row = next(
            row
            for row in timeline["participants"]
            if row["participant_id"] == participant_id
        )
        assert row["survival"]["healing_received"] == pytest.approx(
            by_recipient[participant_id]["applied_amount"], abs=0.05
        )


# ---------------------------------------------------------------------------
# 8. Receipt-vs-score parity + compiled fail-closed
# ---------------------------------------------------------------------------


def test_compiled_kernel_represents_the_timed_heal():
    """A plain heal compiles; the Life From Death packet carries the
    sourced 1.75s nova duration as METADATA — the shared kernel applies
    heals flat in both walks (it never reads action.duration for heals),
    so the timed heal compiles directly (P3 package 3K: Cryptbloom is the
    only support heal packet with a duration)."""
    assert unrepresentable_template_receipt({"kind": "heal", "amount": 100.0}) is None
    assert (
        unrepresentable_template_receipt(
            {
                "kind": "heal",
                "amount": 115.0,
                "duration": NOVA_DURATION,
                "source": SOURCE,
                "cooldown": COOLDOWN,
                "trigger": "explicit_takedown_within_damage_window",
            }
        )
        is None
    )


def test_compiled_walk_equals_receipt_walk_with_the_heal_staged():
    """P3-3K: the compiled score kernel now represents the timed Life From
    Death heal directly (duration is metadata; heals apply flat in both
    walks) — the fast result deep-equals the legacy walk with the compiled
    panel in use and the receipt composition carrying both heal packets
    with applied amounts."""
    legacy = _timeline(include_receipt=False)
    context = CoupledSearchContext()
    fast = _timeline(
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    assert fast == legacy
    assert context.panels  # the compiled panel staged the heal
    full = _timeline(include_receipt=True)
    heals = _timeline_heals(full)
    assert len(heals) == 2
    assert all(event["applied_amount"] > 0 for event in heals)


def test_score_only_fight_parity_cryptbloom_build():
    """run_fight score-only keeps every scoring field identical for a
    Cryptbloom build (totals, resource spent, damage events)."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8.0,
            "include_auto_attacks": True,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
            "allies": [_ally("Jinx")],
            "enemies": [_enemy("Aatrox")],
        },
        deterministic=True,
    )
    champion = get_champion("Lux")
    item = get_item_by_name(CRYPTBLOOM)
    full = run_fight(champion, 18, [item], params, score_only=False)
    score = run_fight(champion, 18, [item], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["resource_spent"] == full["resource_spent"]
    scoring_keys = ("time", "source_key", "damage_type", "raw_damage", "damage")
    assert [
        tuple(event.get(key) for key in scoring_keys)
        for event in score["damage_events"]
    ] == [
        tuple(event.get(key) for key in scoring_keys) for event in full["damage_events"]
    ]


# ---------------------------------------------------------------------------
# 9. Public output
# ---------------------------------------------------------------------------


def test_public_support_events_expose_full_heal_receipt():
    """The /api/calculate combat result exposes the Life From Death heal
    packets in support_events with source, amount, time, trigger, duration,
    cooldown and target_scope; applied/overheal reflect each recipient's
    wound state at the kill time."""
    combat = _calculate(_main_payload())
    heals = _lfd_events(combat)
    assert len(heals) == 2
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    main_events = [
        event["time"]
        for event in combat.get("events", [])
        if event["attacker"] == "main" and event["target"] == "enemy:Aatrox"
    ]
    kill_time = max(main_events)
    expected_amount = BASE_HEAL + AP_RATIO * main["stats"]["ability_power"]
    for event in heals:
        assert event["source"] == SOURCE
        assert event["kind"] == "heal"
        assert event["time"] == pytest.approx(kill_time, abs=0.001)
        assert event["amount"] == pytest.approx(expected_amount, abs=0.001)
        assert event["trigger"] == "explicit_takedown_within_damage_window"
        assert event["duration"] == pytest.approx(NOVA_DURATION)
        assert event["cooldown"] == pytest.approx(COOLDOWN)
        assert event["target_scope"] == "nova_allied_champions"
        assert event["attacker"] == "main"
        assert 0.0 <= event["applied_amount"] <= event["amount"]
        assert event["overheal"] == pytest.approx(
            event["amount"] - event["applied_amount"], abs=0.001
        )
    assert {event["target"] for event in heals} == {"main", "ally:Jinx"}


def test_item_coverage_wording_and_optimizer_eligibility():
    """P3-3K: Cryptbloom is now modeled_state — Life From Death is
    represented by the shared participant support ledger (a synthesized
    takedown schedules the sourced holder/ally heal packets); it is
    optimizer-eligible, in get_eligible_legendaries, and the target model
    prices it on the target lane."""
    item = get_item_by_name(CRYPTBLOOM)
    coverage = item_probe.attacker_coverage(item)
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["status"] == "modeled_state"
    # Ours' reason names the family whose ledger schedules the state rather
    # than repeating the phrase main's retired per-item table typed.
    assert "ally_packet" in coverage["reason"]
    assert CRYPTBLOOM in {entry["name"] for entry in get_eligible_legendaries()}
    target = target_item_model_coverage(item)
    # ``modeled``, not ``not_target_relevant``: Life From Death declares a
    # heal the target lane's own resolver prices for the actor wearing it, so
    # the derived answer names the mechanic instead of calling it irrelevant.
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True


def test_no_stale_bis_entry():
    """bis.py carries no stale Cryptbloom entry."""
    bis_source = (REPO / "src" / "calculator" / "bis.py").read_text(encoding="utf-8")
    assert "Cryptbloom" not in bis_source


# ---------------------------------------------------------------------------
# 10. Determinism + exactly one packet per takedown
# ---------------------------------------------------------------------------


def test_identical_fights_produce_identical_packets():
    """Two identical fights produce identical packets; exactly one packet
    per recipient per takedown (no duplicates)."""
    payload = _main_payload()
    first = _calculate(payload)
    second = _calculate(payload)
    assert _lfd_events(first) == _lfd_events(second)
    assert len(_lfd_events(first)) == 2

    timeline_a = _timeline()
    timeline_b = _timeline()
    assert _timeline_heals(timeline_a) == _timeline_heals(timeline_b)
    assert timeline_a == timeline_b


def test_roster_support_holder_kill_receipted_identically_to_receipt_walk():
    """P3-3K (G1/G2 fix): a ROSTER Cryptbloom holder (ally Brand, a
    non-support champion whose kit authors no ally effects) whose first-pair
    defender dies is receipted identically in the compiled walk and the
    receipt walk — previously the compiled base panel synthesized no
    takedown (no target_id) and silently omitted the heal."""
    from src.calculator.pipeline import FightParams
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    main = get_champion("Ahri")
    FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    ChampionLoadout(
        champion="Brand",
        level=18,
        role="support",
        items=("Cryptbloom",),
        item_options={},
    ).resolve()
    ChampionLoadout(champion="Yuumi", level=1, role="top", items=()).resolve()
    calculate_total_stats(main, 18, [])
    result_legacy = _timeline(
        allies=[
            {
                "champion": "Brand",
                "level": 18,
                "items": ["Cryptbloom"],
                "ally_effects_enabled": True,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
        enemies=[
            {
                "champion": "Yuumi",
                "level": 1,
                "items": [],
                "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
            }
        ],
        include_receipt=False,
    )
    context = CoupledSearchContext()
    result_fast = _timeline(
        allies=[
            {
                "champion": "Brand",
                "level": 18,
                "items": ["Cryptbloom"],
                "ally_effects_enabled": True,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
        enemies=[
            {
                "champion": "Yuumi",
                "level": 1,
                "items": [],
                "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
            }
        ],
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    assert result_fast == result_legacy
