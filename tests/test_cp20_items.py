"""CP20 remaining item gaps — quest/economy/state/resource/vision packets.

Covers the six items in ``docs/cp20-remaining-item-gaps.json``:

- Cull: Reap on-hit healing, 100-minion progression, 350-gold payout.
- Phage: Rage melee/ranged movement speed, 2-second duration.
- Runic Compass: 800-gold Support Quest, Shared Riches, Ward active.
- Tear of the Goddess: Manaflow timing, 3/6 bonus-mana triggers, 360 cap,
  minion-only Helping Hand boundary.
- Umbral Glaive: Blackout vision state, unseen gate, trigger window, typed
  Nightstalker true damage.
- World Atlas: 400-gold Support Quest, Shared Riches, Ward active.

Every numeric value is asserted through the typed ``item_effects`` accessors
(no literals at call sites); packet values come from the registry.
"""

from types import SimpleNamespace

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    _STATIC_ITEM_EFFECTS,
    _PARSEABLE_ITEM_KEYS,
    _STATIC_ITEM_EFFECTS,
    first_auto_state_ready,
    item_state_receipts,
    required_effect_value,
    resolve_damage_effects,
)
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.resource_ledger import TearDeclaration, TearManaflow
from src.calculator.participant_timeline import build_participant_timeline
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_coverage import require_calculation_item_coverage

from tests import item_probe


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    item_options: dict | None = None,
    stats: dict | None = None,
):
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats=stats or {"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=SimpleNamespace(
            item_options=item_options or {},
            ally_effects_enabled=True,
        ),
    )


def _tear_ledger_result(
    owner: str,
    cast_times: tuple[float, ...],
    *,
    authored_bonus_mana: float = 0.0,
) -> dict:
    """Build the fight-result resource_ledger section through the kernel.

    The engine's mana ledger is the single source of truth for Manaflow
    (P3 slice 1): each authored cast at ``cast_times`` is a proven accepted
    eligible hit (the engine only drives hits for accepted casts), so the
    kernel's ``TearManaflow.hit`` produces the same receipts the packet
    projection consumes.
    """
    tear = TearManaflow(
        TearDeclaration(), owner=owner, authored_bonus_mana=authored_bonus_mana
    )
    hits = []
    for sequence, cast_time in enumerate(cast_times):
        receipt, _event = tear.hit(time=cast_time, hit_identity=f"cast-{sequence + 1}")
        hits.append(receipt)
    return {
        "cast_timeline": [{"time": cast_time} for cast_time in cast_times],
        "auto_attack_schedule": {"window_seconds": 24.0},
        "resource_ledger": {
            "contract": "resource_ledger_v1",
            "owner": owner,
            "kind": "mana",
            "tear": {
                "declaration": tear.declaration.public(),
                "authored_bonus_mana": authored_bonus_mana,
                "hits": hits,
                "use_count": tear.use_count,
                "bonus_total": tear.bonus_total,
                "stored_charges": tear.stored_charges,
            },
        },
    }


# ---------------------------------------------------------------------------
# Cull — Reap on-hit healing + 100-minion progression + 350-gold payout
# ---------------------------------------------------------------------------


def test_cull_typed_values_match_the_cached_wiki_branches():
    assert required_effect_value("Cull", "health_per_on_hit") == pytest.approx(3.0)
    assert required_effect_value("Cull", "reap_gold_per_minion") == pytest.approx(1.0)
    assert required_effect_value("Cull", "reap_max_gold") == pytest.approx(100.0)
    assert required_effect_value("Cull", "reap_completion_gold") == pytest.approx(350.0)
    cached = get_item_by_name("Cull")
    branch = " ".join(
        str(b)
        for passive in cached.get("passives", [])
        if passive.get("name") == "Reap"
        for b in passive.get("branches", [])
    )
    assert "maximum" in branch and "100" in branch and "350" in branch


def test_cull_reap_on_hit_heal_is_a_typed_health_packet():
    """The declaration owns the number; the legacy projection no longer
    carries a second copy of it (SD9)."""
    from src.calculator.item_behavior import OnHitHealRule
    from src.calculator.interpreters.sustain import declared_sustain

    slot = declared_sustain(["Cull"], OnHitHealRule)
    assert slot.owner == "Cull"
    assert slot.value("amount") == pytest.approx(
        required_effect_value("Cull", "health_per_on_hit")
    )
    assert not hasattr(
        resolve_damage_effects([get_item_by_name("Cull")]), "on_hit_heals"
    )


def test_cull_reap_economy_packet_pays_progression_and_completion():
    holder = _actor(
        "main:Ahri",
        "main",
        ("Cull",),
        item_options={"Cull": {"reap_minion_kills": 100}},
    )
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(holder, {}, [holder, enemy])

    reap = [packet for packet in packets if packet["source"] == "Cull — Reap"]
    assert len(reap) == 1
    # 100 minions x 1 gold + the sourced 350-gold completion payout.
    assert reap[0]["gold_amount"] == pytest.approx(
        required_effect_value("Cull", "reap_max_gold")
        * required_effect_value("Cull", "reap_gold_per_minion")
        + required_effect_value("Cull", "reap_completion_gold")
    )
    assert reap[0]["completion_granted"] is True
    assert reap[0]["minion_kills"] == pytest.approx(100.0)


def test_cull_progression_is_capped_at_100_minions():
    holder = _actor(
        "main:Ahri",
        "main",
        ("Cull",),
        item_options={"Cull": {"reap_minion_kills": 250}},
    )
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(holder, {}, [holder, enemy])
    reap = [packet for packet in packets if packet["source"] == "Cull — Reap"]
    assert reap[0]["minion_kills"] == pytest.approx(100.0)
    assert reap[0]["gold_amount"] == pytest.approx(450.0)


# ---------------------------------------------------------------------------
# Phage — Rage melee/ranged movement speed, 2-second duration
# ---------------------------------------------------------------------------


def test_phage_rage_emits_one_timed_movement_packet_per_authored_auto():
    holder = _actor(
        "main:Ahri",
        "main",
        ("Phage",),
        stats={"is_melee": False, "mana": 1000.0, "max_mana": 1000.0},
    )
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(
        holder,
        {
            "damage_events": [
                {"time": 0.0, "source_key": "auto_attacks", "damage": 10.0},
                {"time": 1.0, "source_key": "auto_attacks", "damage": 10.0},
            ]
        },
        [holder, enemy],
    )

    rage = [packet for packet in packets if packet["source"] == "Phage — Rage"]
    assert [packet["time"] for packet in rage] == [0.0, 1.0]
    assert all(
        packet["bonus_move_speed_percent"]
        == pytest.approx(required_effect_value("Phage", "rage_bonus_move_speed_ranged"))
        for packet in rage
    )
    assert all(
        packet["duration"]
        == pytest.approx(required_effect_value("Phage", "rage_duration"))
        for packet in rage
    )
    assert rage[0]["kind"] == "movement"


def test_phage_rage_uses_the_melee_speed_for_melee_holders():
    melee = _actor(
        "main:Garen",
        "main",
        ("Phage",),
        stats={"is_melee": True, "mana": 0.0, "max_mana": 0.0},
    )
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(
        melee,
        {"damage_events": [{"time": 0.0, "source_key": "auto_attacks"}]},
        [melee, enemy],
    )
    rage = [packet for packet in packets if packet["source"] == "Phage — Rage"]
    assert rage[0]["bonus_move_speed_percent"] == pytest.approx(
        required_effect_value("Phage", "rage_bonus_move_speed_melee")
    )
    # Melee and ranged values are distinct sourced branches.
    assert required_effect_value(
        "Phage", "rage_bonus_move_speed_melee"
    ) != required_effect_value("Phage", "rage_bonus_move_speed_ranged")


# ---------------------------------------------------------------------------
# Runic Compass / World Atlas — Support Quest + Shared Riches + Ward active
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quest_item", "threshold", "minion_gold", "melee_gold", "ranged_gold"),
    [
        ("World Atlas", 400.0, 15.0, 22.0, 20.0),
        ("Runic Compass", 800.0, 20.0, 24.0, 22.0),
    ],
)
def test_support_quest_typed_thresholds_match_the_cache(
    quest_item, threshold, minion_gold, melee_gold, ranged_gold
):
    assert required_effect_value(
        quest_item, "support_quest_threshold"
    ) == pytest.approx(threshold)
    assert required_effect_value(quest_item, "shared_riches_interval") == pytest.approx(
        20.0
    )
    assert required_effect_value(
        quest_item, "shared_riches_gold_minion"
    ) == pytest.approx(minion_gold)
    assert required_effect_value(
        quest_item, "shared_riches_gold_melee"
    ) == pytest.approx(melee_gold)
    assert required_effect_value(
        quest_item, "shared_riches_gold_ranged"
    ) == pytest.approx(ranged_gold)
    cached = get_item_by_name(quest_item)
    support_quest = next(
        passive
        for passive in cached.get("passives", [])
        if passive.get("name") == "Support Quest"
    )
    assert str(threshold).split(".")[0] in " ".join(
        str(b) for b in support_quest.get("branches", [])
    )


@pytest.mark.parametrize("quest_item", ["World Atlas", "Runic Compass"])
def test_support_quest_emits_economy_and_ward_vision_packets(quest_item):
    threshold = required_effect_value(quest_item, "support_quest_threshold")
    holder = _actor(
        "main:Ahri",
        "main",
        (quest_item,),
        item_options={
            quest_item: {"shared_riches_gold": int(threshold), "ward_uses": 3}
        },
    )
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(holder, {}, [holder, enemy])

    shared = [p for p in packets if p["source"] == f"{quest_item} — Shared Riches"]
    assert len(shared) == 1
    assert shared[0]["gold_amount"] == pytest.approx(threshold)
    assert shared[0]["quest_complete"] is True
    assert shared[0]["shared_riches_interval"] == pytest.approx(20.0)
    assert shared[0]["shared_riches_gold_melee"] == pytest.approx(
        required_effect_value(quest_item, "shared_riches_gold_melee")
    )
    wards = [p for p in packets if p["source"] == f"{quest_item} — Ward"]
    assert len(wards) == 1
    assert wards[0]["ward_uses"] == pytest.approx(3.0)
    assert wards[0]["ward_charges"] == pytest.approx(
        required_effect_value(quest_item, "ward_charges")
    )


# ---------------------------------------------------------------------------
# Tear of the Goddess — Manaflow timing, 3/6 triggers, 360 cap, Helping Hand
# ---------------------------------------------------------------------------


def test_tear_manaflow_typed_values_match_the_cached_branch():
    assert required_effect_value(
        "Tear of the Goddess", "manaflow_charge_interval"
    ) == pytest.approx(8.0)
    assert required_effect_value(
        "Tear of the Goddess", "manaflow_max_charges"
    ) == pytest.approx(4.0)
    assert required_effect_value(
        "Tear of the Goddess", "manaflow_bonus_mana_per_trigger"
    ) == pytest.approx(3.0)
    assert required_effect_value(
        "Tear of the Goddess", "manaflow_bonus_mana_per_champion"
    ) == pytest.approx(6.0)
    assert required_effect_value(
        "Tear of the Goddess", "manaflow_bonus_mana_max"
    ) == pytest.approx(360.0)
    assert required_effect_value(
        "Tear of the Goddess", "helping_hand_minion_damage"
    ) == pytest.approx(5.0)


def test_tear_manaflow_emits_timed_resource_packets_at_the_sourced_cadence():
    holder = _actor("main:Ahri", "main", ("Tear of the Goddess",))
    enemy = _actor("enemy:Aatrox", "enemy", ())
    result = _tear_ledger_result("main:Ahri", (1.0, 9.0, 17.0))
    packets = derive_item_support_effects(holder, result, [holder, enemy])

    manaflow = [p for p in packets if p["source"] == "Tear of the Goddess — Manaflow"]
    # One charge banks at t=0, the next at t=8, the next at t=16; each
    # authored cast consumes the next available charge in time order.
    assert [p["time"] for p in manaflow] == [1.0, 9.0, 17.0]
    assert [p["amount"] for p in manaflow] == [6.0, 6.0, 6.0]
    assert [p["bonus_mana_total"] for p in manaflow] == [6.0, 12.0, 18.0]
    assert all(
        p["bonus_mana_cap"]
        == pytest.approx(
            required_effect_value("Tear of the Goddess", "manaflow_bonus_mana_max")
        )
        for p in manaflow
    )
    assert all(p["kind"] == "resource" for p in manaflow)
    assert all(
        p["manaflow_bonus_mana_per_trigger"] == pytest.approx(3.0)
        and p["manaflow_bonus_mana_per_champion"] == pytest.approx(6.0)
        for p in manaflow
    )
    assert all(p["target_scope"] == "self" for p in manaflow)


def test_tear_manaflow_never_invents_casts_and_respects_the_cap():
    holder = _actor("main:Ahri", "main", ("Tear of the Goddess",))
    enemy = _actor("enemy:Aatrox", "enemy", ())
    no_casts = derive_item_support_effects(
        holder,
        {"cast_timeline": [], "auto_attack_schedule": {"window_seconds": 24.0}},
        [holder, enemy],
    )
    assert not [p for p in no_casts if p["kind"] == "resource"]

    # An already-maxed authored state leaves no room inside the fight window:
    # the ledger denies every hit with cap_reached, so no accepted hit exists
    # to project a packet from.
    maxed = _actor(
        "main:Ahri",
        "main",
        ("Tear of the Goddess",),
        item_options={"Tear of the Goddess": {"manaflow_bonus_mana": 360}},
    )
    maxed_result = _tear_ledger_result("main:Ahri", (1.0,), authored_bonus_mana=360.0)
    maxed_packets = derive_item_support_effects(maxed, maxed_result, [maxed, enemy])
    assert not [p for p in maxed_packets if p["kind"] == "resource"]


def test_tear_manaflow_caps_cumulative_grants_at_the_sourced_remaining_mana():
    holder = _actor(
        "main:Ahri",
        "main",
        ("Tear of the Goddess",),
        item_options={"Tear of the Goddess": {"manaflow_bonus_mana": 356}},
    )
    enemy = _actor("enemy:Aatrox", "enemy", ())
    result = _tear_ledger_result("main:Ahri", (0.5, 8.5), authored_bonus_mana=356.0)
    packets = derive_item_support_effects(holder, result, [holder, enemy])
    manaflow = [p for p in packets if p["source"] == "Tear of the Goddess — Manaflow"]
    assert [p["amount"] for p in manaflow] == [4.0]
    # The packet's public total is the in-fight accrual (authored progress
    # is a separate field); the ledger's full total is 356 + 4 = 360.
    assert manaflow[0]["bonus_mana_total"] == pytest.approx(4.0)
    assert manaflow[0]["authored_bonus_mana"] == pytest.approx(356.0)


def test_tear_state_receipt_exposes_timing_triggers_cap_and_minion_boundary():
    receipts = item_state_receipts(
        [{"name": "Tear of the Goddess"}],
        {"Tear of the Goddess": {"manaflow_bonus_mana": 120}},
        fight_duration_seconds=12.0,
        is_melee=False,
        bonus_mana=120.0,
        max_mana=360.0,
    )
    receipt = receipts[0]
    assert receipt["state"] == "manaflow_progress"
    assert receipt["manaflow_cap"] == pytest.approx(360.0)
    assert receipt["manaflow_charge_interval"] == pytest.approx(8.0)
    assert receipt["manaflow_max_charges"] == pytest.approx(4.0)
    assert receipt["manaflow_bonus_mana_per_trigger"] == pytest.approx(3.0)
    assert receipt["manaflow_bonus_mana_per_champion"] == pytest.approx(6.0)
    assert receipt["helping_hand_minion_only"] is True
    assert receipt["helping_hand_minion_damage"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Umbral Glaive — Blackout vision state + typed Nightstalker true damage
# ---------------------------------------------------------------------------


def test_umbral_nightstalker_true_damage_formula_is_typed():
    from src.calculator.interpreters import charged_strike

    # First-auto strikes compile in the charged-strike interpreter, the one
    # home for that family; ``BuildDamageEffects`` no longer carries them.
    slots = charged_strike.resolve_slots(
        ("Umbral Glaive",),
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert len(slots.first_autos) == 1
    source = slots.first_autos[0].source
    assert source.damage_type == "true"
    from src.calculator.item_effects import DamageInputs

    lethality = 18.0
    assert source.raw_damage(
        DamageInputs({"lethality": lethality}, 18, False, 2000.0, 2000.0)
    ) == pytest.approx(
        required_effect_value("Umbral Glaive", "base")
        + required_effect_value("Umbral Glaive", "lethality_ratio") * lethality
    )


def test_umbral_nightstalker_ready_gate_controls_the_first_auto_packet():
    armed = _actor(
        "main:Ahri",
        "main",
        ("Umbral Glaive",),
        item_options={"Umbral Glaive": {"nightstalker_ready": 1}},
    )
    unarmed = _actor("main:Ahri", "main", ("Umbral Glaive",))
    assert (
        first_auto_state_ready(
            list(armed.items),
            {"Umbral Glaive": {"nightstalker_ready": 1}},
            "Umbral Glaive",
        )
        is True
    )
    assert first_auto_state_ready(list(unarmed.items), {}, "Umbral Glaive") is False


def test_umbral_blackout_emits_a_sourced_vision_receipt_only_when_ready():
    enemy = _actor("enemy:Aatrox", "enemy", ())
    ready = _actor(
        "main:Ahri",
        "main",
        ("Umbral Glaive",),
        item_options={"Umbral Glaive": {"nightstalker_ready": 1}},
        stats={"lethality": 18.0, "is_melee": False},
    )
    packets = derive_item_support_effects(ready, {}, [ready, enemy])
    blackout = [p for p in packets if p["source"] == "Umbral Glaive — Blackout"]
    assert len(blackout) == 1
    assert blackout[0]["kind"] == "vision"
    assert blackout[0]["ward_only"] is True
    assert blackout[0]["ward_hits_modeled"] == 0
    assert blackout[0]["ward_uses"] == 0.0
    assert blackout[0]["unseen_gate_seconds"] == pytest.approx(
        required_effect_value("Umbral Glaive", "nightstalker_unseen_seconds")
    )
    assert blackout[0]["trigger_window_seconds"] == pytest.approx(
        required_effect_value("Umbral Glaive", "nightstalker_trigger_window")
    )
    assert blackout[0]["blackout_duration"] == pytest.approx(
        required_effect_value("Umbral Glaive", "blackout_duration")
    )
    assert blackout[0]["true_damage_on_ward_hit"] == pytest.approx(50.0 + 1.5 * 18.0)

    not_ready = _actor(
        "main:Ahri", "main", ("Umbral Glaive",), stats={"lethality": 18.0}
    )
    assert derive_item_support_effects(not_ready, {}, [not_ready, enemy]) == []


def test_umbral_state_receipt_exposes_the_sourced_windows_and_duration():
    receipts = item_state_receipts(
        [{"name": "Umbral Glaive"}],
        {"Umbral Glaive": {"nightstalker_ready": 1}},
        fight_duration_seconds=4.0,
        is_melee=False,
        lethality=18.0,
    )
    receipt = receipts[0]
    assert receipt["state"] == "nightstalker_ready"
    assert receipt["unseen_window_seconds"] == pytest.approx(1.0)
    assert receipt["trigger_window_seconds"] == pytest.approx(4.0)
    assert receipt["blackout_duration"] == pytest.approx(8.0)
    assert receipt["true_damage"] == pytest.approx(77.0)


# ---------------------------------------------------------------------------
# Registry ownership + optimizer coverage for all six items
# ---------------------------------------------------------------------------


def test_new_typed_keys_have_exactly_one_registry_owner():
    """Every typed key has exactly one owner: the code-owned static table or
    the parser-owned key set, never both and never neither.

    The union is checked against the LIVE registry entry rather than against
    the static table itself: ``_OFFLINE_ITEM_EFFECTS`` retired, and the
    resolved ``ITEM_EFFECTS`` record is what the two tables are supposed to
    partition.
    """
    for item_name in _STATIC_ITEM_EFFECTS:
        static_keys = frozenset(_STATIC_ITEM_EFFECTS[item_name])
        parseable_keys = _PARSEABLE_ITEM_KEYS.get(item_name, frozenset())
        assert static_keys.isdisjoint(parseable_keys), item_name
        assert static_keys | parseable_keys == frozenset(
            ITEM_EFFECTS.get(item_name, {})
        ), item_name


@pytest.mark.parametrize(
    "item_name",
    [
        "Cull",
        "Phage",
        "Runic Compass",
        "Tear of the Goddess",
        "Umbral Glaive",
        "World Atlas",
    ],
)
def test_cp20_items_are_classified_modeled_state_and_optimizer_eligible(item_name):
    item = get_item_by_name(item_name)
    coverage = item_probe.attacker_coverage(item)
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["review_issue_refs"] == []
    require_calculation_item_coverage([item], participant="Attacker")


# ---------------------------------------------------------------------------
# Participant timeline — utility receipts carry economy/vision/resource/movement
# ---------------------------------------------------------------------------


def _timeline(enemy_items=()):
    main = get_champion("Ahri")
    loadout = ChampionLoadout(champion="Ahri", level=18, items=()).resolve()
    params = FightParams.from_request(
        {
            "fight_mode": "timed",
            "fight_duration": 12,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "item_options": {
                "Cull": {"reap_minion_kills": 100},
                "Tear of the Goddess": {"manaflow_bonus_mana": 0},
                "Umbral Glaive": {"nightstalker_ready": 1},
                "Runic Compass": {"shared_riches_gold": 800, "ward_uses": 3},
            },
        },
        deterministic=True,
    )
    items = [
        get_item_by_name(name)
        for name in ("Cull", "Tear of the Goddess", "Umbral Glaive", "Runic Compass")
    ]
    main_stats = calculate_total_stats(
        main,
        18,
        items,
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=enemy_items).resolve()
    return build_participant_timeline(
        main,
        18,
        items,
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses(
            "Ahri", 18, main_stats, items, item_options=params.item_options
        ),
        enemies=[enemy],
        allies=[],
    )


def test_participant_timeline_utility_receipts_cover_cp20_dimensions():
    combat = _timeline()
    utility = combat["utility_outcomes"]["focus"]

    assert utility["economy"]["gold"] == pytest.approx(800.0 + 450.0)
    assert utility["economy"]["event_count"] == 2
    assert utility["vision"]["ward_uses"] == pytest.approx(3.0)
    assert utility["vision"]["blackout"]["event_count"] == 1
    assert utility["vision"]["blackout"]["trigger_windows"] == pytest.approx(1.0)
    assert utility["resource"]["bonus_mana"] == pytest.approx(12.0)
    assert utility["resource"]["event_count"] == 2
    assert {"economy", "vision", "resource"} <= set(utility["applied_dimensions"])

    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    # Resource packets are receipt-only: they must never heal or damage.
    assert main["survival"]["healing_received"] >= 0.0
    assert main["survival"]["ending_health"] == pytest.approx(
        main["survival"]["max_health"]
        - main["survival"]["health_damage"]
        + main["survival"]["healing_received"]
        - main["survival"]["overkill"] * 0.0,
        abs=0.01,
    )


def test_participant_timeline_phage_rage_movement_receipt():
    main = get_champion("Ahri")
    loadout = ChampionLoadout(champion="Ahri", level=18, items=()).resolve()
    params = FightParams.from_request(
        {
            "fight_mode": "timed",
            "fight_duration": 4,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    items = [get_item_by_name("Phage")]
    main_stats = calculate_total_stats(
        main,
        18,
        items,
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
    combat = build_participant_timeline(
        main,
        18,
        items,
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses(
            "Ahri", 18, main_stats, items, item_options=params.item_options
        ),
        enemies=[enemy],
        allies=[],
    )
    utility = combat["utility_outcomes"]["focus"]
    assert utility["movement"]["event_count"] > 0
    assert utility["movement"]["speed_percent_seconds"] > 0.0
    assert "movement" in utility["applied_dimensions"]
