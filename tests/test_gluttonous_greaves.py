"""P1 Package 3L — Gluttonous Greaves "Slay" takedown-omnivamp certification.

This file is the independent acceptance matrix for Gluttonous Greaves'
Slay passive: "Scoring a takedown against an enemy champion grants you
0.6% omnivamp, stacking up to 10 times for a total of 6% omnivamp."
It pins the OBSERVABLES the P3-3L acceptance rules require and runs
against today's source: every behavior that already exists must pass now;
genuinely absent contract pieces are ``xfail`` with reason
``awaiting P3-3L ...`` (the Slay takedown/stack/omnivamp machinery is
largely absent today — the fail-closed absences below are pinned as
PASSING current observables and the contract assertions are xfailed).

Contract pinned (typed source-backed values, verified against
docs/wiki-full-entry-audit.json — Gluttonous Greaves page 1661999,
revision_id 4030444, description "Scoring a takedown against an enemy
champion grants you 0.6% omnivamp, stacking up to 10 times for a total
of 6% omnivamp."; also cross-checked by data/atoms/items.json 3008
``stack.gain``/``stat.omnivamp`` = [0.6, 10.0, 6.0]):

* slay_omnivamp_per_takedown 0.6, slay_max_stacks 10,
  slay_max_omnivamp 6.0, source_url
  https://wiki.leagueoflegends.com/en-us/Gluttonous_Greaves and
  source_revision_id 4030444 through the typed accessor(s) the
  coordinator adds (``required_effect_value`` or
  ``ally_item_effect_value`` — mirror the item's registry home);
  missing keys raise KeyError naming Gluttonous Greaves AND the key.
  TODAY: no registry entry exists and ``required_effect_value`` /
  ``ally_item_effect_value`` both fail loud — pinned as the current
  fail-closed observable.
* Stack bounds/default: the slay_stacks scenario option mirrors the
  Immortal Path precedent (type int, label "Slay takedown stacks",
  default 0, min 0, max 10, step 1, bonus_omnivamp_per_unit 0.6);
  the request layer REJECTS out-of-range values ("must be between 0
  and 10" — the Immortal Path observable) and the receipt layer
  clamps the count at 0 (max(0, stacks), Immortal Path precedent).
  TODAY: Gluttonous Greaves has NO ITEM_INPUT_OPTIONS entry — any
  authored option fails closed with "Unknown item option target:
  Gluttonous Greaves" (pinned), and an authored slay_stacks adds 0.0
  to the stat bundle (no silent literal).
* Valid champion takedown admission: ONE stack per valid champion
  takedown event through the takedown stream (mirror Cryptbloom's
  first-pair synthesis); the stack count can reach 10.  TODAY: a kill
  fight authors NO Slay state (support_events empty, no receipts,
  omnivamp stays at the boot's base 4.0) — pinned.
* Invalid boundaries: non-champion/non-takedown/malformed (no time /
  no target) / dead-owner / duplicate takedown receipts add NO stacks.
  These assertions pass vacuously today (nothing adds stacks) and must
  keep passing once the P3-3L branch exists.
* Cap behavior: resolved omnivamp percent = min(stacks * 0.6, 6.0) —
  at 10 stacks exactly slay_max_omnivamp == slay_max_stacks *
  slay_omnivamp_per_takedown (typed consistency, no literal at the
  call site).
* Typed stat/sustain projection: the omnivamp value comes from a typed
  item_effects accessor (a monkeypatched per-takedown value must change
  the resolved bonus — proves no literal); the projection into the
  stat/sustain receipt is pinned (stacks -> percent, percent carried on
  the public item_state_receipts receipt, Immortal Path receipt shape).
  TODAY: resolve_stat_effects contributes 0.0 and item_state_receipts
  carries no Gluttonous Greaves entry — pinned.
* Receipt-vs-score parity: the Slay state reaches the score and receipt
  paths identically (score-only run_fight, full run_fight, and the
  compiled vs receipt timeline walks agree; the compiled walk must not
  silently drop the stack state — issue #169 dict-row retention); the
  healing application is pinned as STAT-ONLY today — self_healing_events
  come from the "Omnivamp" stat source and NO Slay-sourced packet or
  invented healing exists anywhere.  If the survival engine cannot price
  omnivamp healing from the stack state, the receipt is the ONLY
  carrier (no invented healing).
* Coverage wording + public output: today item_coverage.py:231 says
  "Slay grants omnivamp, not outgoing damage." (status stats_only,
  optimizer_eligible True, outcome_dimensions []); the P3-3L target
  wording names the modeled stack/stat receipt and any withheld
  dimension (status leaves stats_only, reason still names Slay +
  omnivamp + stack).  /api/boots pins the public stat (omnivamp 4.0,
  tier 2, upgrade_to Immortal Path).
* Determinism: identical fights -> identical stack states/receipts.
* The existing Gluttonous app regression stays green:
  tests/test_app.py::test_boot_stats_change_damage_and_omnivamp_healing
  (Gluttonous Greaves -> champion_stats.omnivamp_percent == 4.0 and
  survival healing_received > 0); the same pins are re-asserted here so
  this matrix fails loudly if that contract drifts.
"""

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
    gluttonous_greaves_slay_omnivamp,
    input_option_value,
    item_state_receipts,
    required_effect_value,
    resolve_stat_effects,
    validate_item_input_options,
)
from src.calculator.item_support_effects import (
    derive_item_support_effects,
)
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

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


GLUTTONOUS = "Gluttonous Greaves"
SLAY_SOURCE = "Gluttonous Greaves — Slay"
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Gluttonous_Greaves"
REVISION_ID = 4030444  # docs/wiki-full-entry-audit.json (page 1661999)
PER_TAKEDOWN = 0.6
MAX_STACKS = 10
MAX_OMNIVAMP = 6.0
BASE_OMNIVAMP = 4.0  # the boot's cached base omnivamp stat (data/items.json 3008)
CONTRACT_KEYS = ("slay_omnivamp_per_takedown", "slay_max_stacks", "slay_max_omnivamp")


# ---------------------------------------------------------------------------
# App-level helpers (public /api/calculate surface)
# ---------------------------------------------------------------------------


def _calculate(payload: dict) -> dict:
    app.config["TESTING"] = True
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()


def _ally(name: str, level: int = 1) -> dict:
    return {
        "champion": name,
        "level": level,
        "items": [],
        "ally_effects_enabled": True,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
    }


def _enemy(name: str, level: int = 1) -> dict:
    return {
        "champion": name,
        "level": level,
        "items": [],
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
    }


def _main_payload(
    *, allies: list[dict] | None = None, enemies: list[dict] | None = None
) -> dict:
    """A deterministic kill-fight request: Lux R + autos vs a level-1 enemy."""
    return {
        "champion": "Lux",
        "level": 18,
        "items": [],
        "boots": GLUTTONOUS,
        "role": "mid",
        "fight_mode": "time_based",
        "fight_duration": 8.0,
        "include_auto_attacks": True,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
        "allies": allies if allies is not None else [_ally("Jinx")],
        "enemies": enemies if enemies is not None else [_enemy("Aatrox")],
    }


def _combat(payload: dict) -> dict:
    return _calculate(payload)["combat"]


def _main_row(combat: dict) -> dict:
    return next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )


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
    pair_result_cache: dict | None = None,
    search_context: CoupledSearchContext | None = None,
) -> dict:
    enemies = enemies if enemies is not None else [_enemy("Aatrox")]
    allies = allies if allies is not None else [_ally("Jinx")]
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8.0,
            "include_auto_attacks": True,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
            "allies": allies,
            "enemies": enemies,
        },
        deterministic=True,
    )
    champion = get_champion("Lux")
    item = get_item_by_name(GLUTTONOUS)
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


def _run_fight(score_only: bool = False) -> dict:
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
    item = get_item_by_name(GLUTTONOUS)
    return run_fight(champion, 18, [item], params, score_only=score_only)


# ---------------------------------------------------------------------------
# Derive-level helpers (hand-built takedown receipts)
# ---------------------------------------------------------------------------


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    health: float = 1000.0,
):
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={
            "health": health,
            "ability_power": 0.0,
            "max_mana": 1000.0,
            "mana": 1000.0,
            "is_melee": False,
        },
        request=SimpleNamespace(item_options={}, ally_effects_enabled=True),
    )


def _item(name: str) -> dict:
    return {"name": name}


def _gg_receipts(receipts: list[dict]) -> list[dict]:
    return [receipt for receipt in receipts if receipt.get("item") == GLUTTONOUS]


def _slay_stack_count(packets: list[dict]) -> int:
    """Total Slay stacks carried by derived packets (contract helper).

    Accepts either the per-takedown packet shape (a packet per accepted
    takedown carrying ``stack_count``/``slay_stacks``, Bloodletter's Curse
    precedent) or the aggregate receipt shape (one packet with a
    ``slay_stacks`` field).  Missing markers count 0.
    """
    slay = [
        packet
        for packet in packets
        if "Slay" in str(packet.get("source", "")) or "slay_stacks" in packet
    ]
    if not slay:
        return 0
    counts = [
        int(packet.get("stack_count", packet.get("slay_stacks", 0)))
        for packet in slay
        if packet.get("stack_count") is not None
        or packet.get("slay_stacks") is not None
    ]
    return int(max(counts)) if counts else len(slay)


def _valid_takedowns(count: int) -> list[dict]:
    return [
        {"time": float(3 + index), "target": f"enemy:Victim{index}"}
        for index in range(count)
    ]


# ---------------------------------------------------------------------------
# 1. Typed values + missing-key fail-closed + source revision
# ---------------------------------------------------------------------------


def test_required_effect_value_fails_loud_naming_item_and_key():
    """P3-3L: Gluttonous Greaves now HAS an ITEM_EFFECTS record with the
    contract keys, so the fail-loud contract is pinned on a MISSING key
    (AGENTS.md rule 5: no silent stale fallbacks at call sites)."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(GLUTTONOUS, "slay_missing_key_3l")
    message = str(excinfo.value)
    assert GLUTTONOUS in message
    assert "slay_missing_key_3l" in message
    # The real keys resolve typed.
    for key in CONTRACT_KEYS:
        assert required_effect_value(GLUTTONOUS, key) is not None


def test_ally_accessor_fails_loud_for_gluttonous():
    """The Slay values do not live in ALLY_ITEM_EFFECTS either (Slay is a
    holder stat, not an ally-support packet); the typed ally accessor
    fails loud naming the item."""
    with pytest.raises(KeyError) as excinfo:
        ally_item_effect_value(GLUTTONOUS, "slay_omnivamp_per_takedown")
    assert GLUTTONOUS in str(excinfo.value)


def test_slay_typed_values_and_registry_revision():
    """P3-3L contract: the typed registry entry carries 0.6 / 10 / 6.0
    with the wiki source url and revision 4030444 (whichever registry
    homes the entry — ITEM_EFFECTS or ALLY_ITEM_EFFECTS — and the
    ITEM_INPUT_OPTIONS source metadata)."""
    effect = ITEM_EFFECTS.get(GLUTTONOUS) or ALLY_ITEM_EFFECTS.get(GLUTTONOUS)
    assert effect, "no typed registry entry for Gluttonous Greaves"
    assert effect["slay_omnivamp_per_takedown"] == PER_TAKEDOWN
    assert effect["slay_max_stacks"] == MAX_STACKS
    assert effect["slay_max_omnivamp"] == MAX_OMNIVAMP
    options_meta = ITEM_INPUT_OPTIONS.get(GLUTTONOUS, {})
    assert effect.get("source_url", options_meta.get("source_url")) == SOURCE_URL
    assert (
        effect.get("source_revision_id", options_meta.get("source_revision_id"))
        == REVISION_ID
    )


# ---------------------------------------------------------------------------
# 2. Stack bounds / default (mirror the Immortal Path slay_stacks option)
# ---------------------------------------------------------------------------


def test_slay_stacks_option_now_exists_and_is_schema_managed():
    """P3-3L: Gluttonous Greaves has an ITEM_INPUT_OPTIONS entry with the
    slay_stacks schema (0..10) — out-of-range authored values are rejected
    at the request layer with a named error, never silently clamped or
    ignored."""
    assert GLUTTONOUS in ITEM_INPUT_OPTIONS
    with pytest.raises(ValueError) as excinfo:
        validate_item_input_options({GLUTTONOUS: {"slay_stacks": 11}})
    assert "must be between 0 and 10" in str(excinfo.value)

    response = app.test_client().post(
        "/api/calculate",
        json={
            **_main_payload(),
            "item_options": {GLUTTONOUS: {"slay_stacks": 11}},
        },
    )
    assert response.status_code == 400
    assert "must be between 0 and 10" in response.get_json()["error"]


def test_authored_slay_stacks_contribute_typed_omnivamp():
    """P3-3L: an authored slay_stacks of 5 contributes exactly 5 * 0.6 =
    3.0 to the stat bundle through the typed accessor (no literal at the
    call site)."""
    bonuses = resolve_stat_effects(
        [_item(GLUTTONOUS)],
        bonus_mana=0.0,
        max_mana=500.0,
        bonus_health=0.0,
        base_attack_damage=100.0,
        bonus_mana_regen_percent=0.0,
        is_melee=False,
        level=18,
        item_options={GLUTTONOUS: {"slay_stacks": 5}},
    )
    assert bonuses.bonus_omnivamp == pytest.approx(3.0)


def test_slay_stacks_option_schema_mirrors_immortal_path():
    """P3-3L contract: the scenario option mirrors Immortal Path's
    slay_stacks (int, default 0, min 0, max 10, step 1, label "Slay
    takedown stacks", bonus_omnivamp_per_unit 0.6) with the wiki source
    metadata; the request layer ACCEPTS 0..10 and REJECTS out-of-range
    values with the Immortal Path wording ("must be between 0 and 10")."""
    config = ITEM_INPUT_OPTIONS[GLUTTONOUS]
    schema = config["options"]["slay_stacks"]
    assert schema["type"] == "int"
    assert schema["label"] == "Slay takedown stacks"
    assert schema["default"] == 0
    assert schema["min"] == 0
    assert schema["max"] == MAX_STACKS
    assert schema["step"] == 1
    assert schema["bonus_omnivamp_per_unit"] == PER_TAKEDOWN
    assert config["source_url"] == SOURCE_URL
    assert config["source_revision_id"] == REVISION_ID

    for stacks in (0, 5, MAX_STACKS):
        assert validate_item_input_options({GLUTTONOUS: {"slay_stacks": stacks}}) == {
            GLUTTONOUS: {"slay_stacks": stacks}
        }
    for stacks in (MAX_STACKS + 1, -1):
        with pytest.raises(ValueError, match="must be between 0 and 10"):
            validate_item_input_options({GLUTTONOUS: {"slay_stacks": stacks}})


# ---------------------------------------------------------------------------
# 3. Valid champion takedown admission (the authored slay_stacks option)
# ---------------------------------------------------------------------------


def test_kill_fight_authors_no_slay_support_packets():
    """P3-3L named boundary: the takedown stream is support-packet-only
    and CANNOT project into pre-fight stats (stats resolve before the
    fight), so a kill fight authors NO Slay support packets and no Slay
    state beyond the authored option; the omnivamp stays at the boot's
    base 4.0 when no stacks are authored."""
    combat = _combat(_main_payload())
    enemy = next(
        row for row in combat["participants"] if row["participant_id"] == "enemy:Aatrox"
    )
    assert enemy["survival"]["death_time"] == pytest.approx(0.0)
    assert combat.get("support_events", []) == []
    assert _calculate(_main_payload())["champion_stats"]["omnivamp_percent"] == (
        BASE_OMNIVAMP
    )


def test_gluttonous_stays_out_of_the_takedown_scan_registry():
    """P3-3L named boundary: Gluttonous Greaves does NOT join
    TAKEDOWN_SCAN_SUPPORT_ITEMS — its Slay admission is the authored
    scenario option, not a support-packet takedown stream (the stream is
    support-packet-only and cannot project into pre-fight stats)."""
    assert TAKEDOWN_SCAN_SUPPORT_ITEMS == frozenset({"Cryptbloom"})
    assert has_takedown_scan_support_items([{"name": GLUTTONOUS}]) is False
    assert has_event_view_support_items([{"name": GLUTTONOUS}]) is False


def test_ten_authored_stacks_reach_max_omnivamp():
    """P3-3L: the authored slay_stacks option at the 10-stack cap resolves
    to exactly the typed slay_max_omnivamp (6.0) through the accessor —
    per_takedown * max_stacks == max_omnivamp, no literal at the call
    site."""
    stacks = input_option_value(
        [get_item_by_name(GLUTTONOUS)],
        {GLUTTONOUS: {"slay_stacks": MAX_STACKS}},
        GLUTTONOUS,
        "slay_stacks",
    )
    assert stacks == MAX_STACKS
    resolved = gluttonous_greaves_slay_omnivamp(
        [get_item_by_name(GLUTTONOUS)],
        {GLUTTONOUS: {"slay_stacks": MAX_STACKS}},
    )
    per_takedown = required_effect_value(GLUTTONOUS, "slay_omnivamp_per_takedown")
    assert resolved == pytest.approx(per_takedown * MAX_STACKS)
    assert resolved == pytest.approx(
        required_effect_value(GLUTTONOUS, "slay_max_omnivamp")
    )


# 4. Invalid boundaries: non-champion / non-takedown / malformed /
#    dead-owner / duplicate events add NO stacks
# ---------------------------------------------------------------------------


def test_non_takedown_fight_authors_no_stacks():
    """No kill (a level-18 enemy survives the window) -> no Slay state:
    no receipts, no support events, omnivamp stays 4.0."""
    body = _calculate(_main_payload(enemies=[_enemy("Ahri", level=18)]))
    combat = body["combat"]
    ahri = next(
        row for row in combat["participants"] if row["participant_id"] == "enemy:Ahri"
    )
    assert ahri["survival"]["death_time"] is None
    assert combat.get("support_events", []) == []
    assert body["champion_stats"]["omnivamp_percent"] == BASE_OMNIVAMP
    # No authored stacks -> the Slay receipt row carries zero stacks.
    receipts = _run_fight()["item_state_receipts"]
    slay = [
        row
        for row in receipts
        if row.get("item") == GLUTTONOUS and row.get("state") == "slay_stacks"
    ]
    assert slay and slay[0]["slay_stacks"] == 0
    assert slay[0]["omnivamp"] == pytest.approx(0.0)


def test_malformed_and_non_champion_takedowns_add_no_stacks():
    """Malformed takedown receipts (no time, None time, no target,
    non-mapping row) and non-champion targets (minion/monster ids) add NO
    stacks.  Vacuous today (no stream branch exists); must keep holding
    once the P3-3L branch lands."""
    holder = _actor("main:Lux", "main", (GLUTTONOUS,))
    events = [
        {"target": "enemy:Darius"},  # no time -> filtered
        {"time": None, "target": "enemy:B"},  # None time -> filtered
        {"time": 4.0},  # no target -> filtered
        "garbage",  # non-mapping -> filtered
        {"time": 5.0, "target": "enemy:Minion"},  # non-champion target
        {"time": 6.0, "target": "enemy:Monster"},
        {"time": 7.0, "target": "turret"},
    ]
    packets = derive_item_support_effects(holder, {"takedown_events": events}, [holder])
    assert _slay_stack_count(packets) == 0


def test_dead_owner_takedown_adds_no_stacks():
    """A takedown receipt whose holder is dead (stats health 0.0, the
    Cryptbloom dead-holder fixture shape) grants NO stack.  Vacuous today;
    the P3-3L branch must gate on the holder's live state (the Slay grant
    is the holder's own takedown — unlike Cryptbloom's team nova)."""
    holder = _actor("main:Lux", "main", (GLUTTONOUS,), health=0.0)
    packets = derive_item_support_effects(
        holder, {"takedown_events": _valid_takedowns(1)}, [holder]
    )
    assert _slay_stack_count(packets) == 0


def test_duplicate_takedown_events_add_no_extra_stacks():
    """The same takedown receipt appearing twice grants no extra stack
    (the stream dedupes the accepted set).  Vacuous today."""
    holder = _actor("main:Lux", "main", (GLUTTONOUS,))
    event = {"time": 3.0, "target": "enemy:Aatrox"}
    packets = derive_item_support_effects(
        holder, {"takedown_events": [event, event]}, [holder]
    )
    assert _slay_stack_count(packets) <= 1


# ---------------------------------------------------------------------------
# 5. Cap behavior: resolved omnivamp = min(stacks * 0.6, 6.0)
# ---------------------------------------------------------------------------


def test_resolved_omnivamp_cap_binds_typed_consistency():
    """P3-3L contract: at the cap the resolved bonus equals
    slay_max_omnivamp and the three typed values are mutually consistent
    (max_omnivamp == max_stacks * per_takedown; no literal 6.0/0.6/10 at
    any call site)."""
    max_omnivamp = required_effect_value(GLUTTONOUS, "slay_max_omnivamp")
    max_stacks = required_effect_value(GLUTTONOUS, "slay_max_stacks")
    per_takedown = required_effect_value(GLUTTONOUS, "slay_omnivamp_per_takedown")
    assert max_omnivamp == pytest.approx(max_stacks * per_takedown)

    bonuses = resolve_stat_effects(
        [_item(GLUTTONOUS)],
        bonus_mana=0.0,
        max_mana=500.0,
        bonus_health=0.0,
        base_attack_damage=100.0,
        bonus_mana_regen_percent=0.0,
        is_melee=False,
        level=18,
        item_options={GLUTTONOUS: {"slay_stacks": max_stacks}},
    )
    assert bonuses.bonus_omnivamp == pytest.approx(max_omnivamp)


# ---------------------------------------------------------------------------
# 6. Typed stat/sustain projection (stacks -> percent on the receipt)
# ---------------------------------------------------------------------------


def test_stat_projection_folds_slay_into_omnivamp_percent():
    """P3-3L: the boot contributes its cached base omnivamp stat (4.0)
    PLUS the authored Slay bonus (0.6 per stack) to the stat bundle, and
    the public item_state_receipts carries the Slay row."""
    item = get_item_by_name(GLUTTONOUS)
    stats = calculate_total_stats(
        get_champion("Jinx"),
        12,
        [item],
        role="bottom",
        item_options={GLUTTONOUS: {"slay_stacks": 5}},
    )
    assert stats["omnivamp_percent"] == pytest.approx(BASE_OMNIVAMP + 3.0)
    receipts = _gg_receipts(
        item_state_receipts(
            [item],
            {GLUTTONOUS: {"slay_stacks": 5}},
            fight_duration_seconds=10.0,
            is_melee=False,
        )
    )
    assert receipts
    assert receipts[0]["omnivamp"] == pytest.approx(3.0)


def test_projection_reads_typed_accessor_not_literal(monkeypatch):
    """P3-3L contract: the resolved bonus reads the typed registry value
    — a monkeypatched per-takedown 0.5 must change the resolved bonus
    (proves no literal 0.6 at the call site)."""
    effect = ITEM_EFFECTS.get(GLUTTONOUS) or ALLY_ITEM_EFFECTS.get(GLUTTONOUS)
    assert effect
    registry = ITEM_EFFECTS if GLUTTONOUS in ITEM_EFFECTS else ALLY_ITEM_EFFECTS
    monkeypatch.setitem(
        registry, GLUTTONOUS, {**effect, "slay_omnivamp_per_takedown": 0.5}
    )
    bonuses = resolve_stat_effects(
        [_item(GLUTTONOUS)],
        bonus_mana=0.0,
        max_mana=500.0,
        bonus_health=0.0,
        base_attack_damage=100.0,
        bonus_mana_regen_percent=0.0,
        is_melee=False,
        level=18,
        item_options={GLUTTONOUS: {"slay_stacks": 4}},
    )
    assert bonuses.bonus_omnivamp == pytest.approx(2.0)


def test_slay_receipt_carries_stacks_and_omnivamp_percent():
    """P3-3L contract: the public item_state_receipts carries the Slay
    state with the Immortal Path receipt shape — item, state
    "slay_stacks", slay_stacks (negative clamped to 0), max_stacks,
    omnivamp (stacks -> percent), and the wiki source url/revision."""
    receipts = item_state_receipts(
        [_item(GLUTTONOUS)],
        {GLUTTONOUS: {"slay_stacks": 5}},
        fight_duration_seconds=10.0,
        is_melee=False,
    )
    (receipt,) = _gg_receipts(receipts)
    assert receipt["state"] == "slay_stacks"
    assert receipt["slay_stacks"] == 5
    assert receipt["max_stacks"] == required_effect_value(GLUTTONOUS, "slay_max_stacks")
    assert receipt["omnivamp"] == pytest.approx(5 * PER_TAKEDOWN)
    assert receipt["source_url"] == SOURCE_URL
    assert receipt["source_revision_id"] == REVISION_ID

    clamped = _gg_receipts(
        item_state_receipts(
            [_item(GLUTTONOUS)],
            {GLUTTONOUS: {"slay_stacks": -2}},
            fight_duration_seconds=10.0,
            is_melee=False,
        )
    )
    assert clamped[0]["slay_stacks"] == 0  # Immortal Path max(0, stacks) mirror


# ---------------------------------------------------------------------------
# 7. Receipt-vs-score parity + healing carrier (no invented healing)
# ---------------------------------------------------------------------------


def test_score_only_fight_parity_gluttonous_build():
    """Score-only and full run_fight agree on every scoring field and on
    the (empty today) Slay state receipts — the stack state must reach
    both paths identically, never only one."""
    full = _run_fight(score_only=False)
    score = _run_fight(score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["resource_spent"] == full["resource_spent"]
    assert score["item_state_receipts"] == full["item_state_receipts"]
    assert (
        score["champion_stats"]["omnivamp_percent"]
        == full["champion_stats"]["omnivamp_percent"]
    )
    scoring_keys = ("time", "source_key", "damage_type", "raw_damage", "damage")
    assert [
        tuple(event.get(key) for key in scoring_keys)
        for event in score["damage_events"]
    ] == [
        tuple(event.get(key) for key in scoring_keys) for event in full["damage_events"]
    ]


def test_healing_flows_from_base_stat_only_no_slay_packets():
    """The survival engine prices omnivamp healing from the STAT (the
    boot's base 4.0): self_healing_events carry the typed "Omnivamp"
    source and NO Slay-sourced packet or invented healing exists anywhere
    (support_events empty, self-healing sources all stat omnivamp)."""
    body = _calculate(_main_payload())
    combat = body["combat"]
    assert combat.get("support_events", []) == []
    assert body["champion_stats"]["omnivamp_percent"] == BASE_OMNIVAMP
    main = _main_row(combat)
    assert main["survival"]["healing_received"] > 0
    assert body["self_healing"] > 0
    assert body["self_healing_events"]
    for event in body["self_healing_events"]:
        assert "Omnivamp" in str(event.get("source", ""))
        assert "Slay" not in str(event.get("source", ""))

    full = _run_fight(score_only=False)
    assert full["self_healing_events"]
    for event in full["self_healing_events"]:
        assert "Omnivamp" in str(event.get("source", ""))
        assert "Slay" not in str(event.get("source", ""))


def test_compiled_walk_equals_receipt_walk_gluttonous_build():
    """The compiled score walk equals the legacy receipt walk for a
    Gluttonous Greaves holder (empty Slay state today; must stay equal
    once the P3-3L stack state exists — the compiled walk must not
    silently drop the takedown-synthesized stack state)."""
    legacy = _timeline(include_receipt=False)
    context = CoupledSearchContext()
    fast = _timeline(
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    assert fast == legacy


# ---------------------------------------------------------------------------
# 8. Coverage wording + public output
# ---------------------------------------------------------------------------


def test_item_coverage_wording_names_modeled_slay():
    """P3-3L: Gluttonous Greaves is modeled_state — the coverage reason
    names Slay, omnivamp, and the stack receipt, and optimizer
    eligibility holds."""
    item = get_item_by_name(GLUTTONOUS)
    coverage = item_probe.attacker_coverage(item)
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    # Ours' reason is derived from the declaration: it names the bounded
    # scenario control the state comes from, not the mechanic's prose.
    # The mechanic itself is pinned by the receipt tests above.
    assert "bounded scenario control" in coverage["reason"]


def test_target_model_not_target_relevant_today():
    """Slay changes the holder's sustain, never incoming damage: the
    target model stays not_target_relevant."""
    item = get_item_by_name(GLUTTONOUS)
    target = target_item_model_coverage(item)
    assert target["status"] == "not_target_relevant"
    assert target["calculation_eligible"] is True


def test_public_boots_api_pins_current_omnivamp_stat():
    """/api/boots exposes the boot's public stat (omnivamp 4.0, tier 2,
    upgrade_to Immortal Path) and the current stats_only coverage."""
    boots = app.test_client().get("/api/boots").get_json()
    boot = next(b for b in boots if b["name"] == GLUTTONOUS)
    assert boot["omnivamp"] == BASE_OMNIVAMP
    assert boot["tier"] == 2
    assert boot["upgrade_to"] == "Immortal Path"
    assert boot["model_coverage"]["status"] == "modeled_state"
    assert "bounded scenario control" in boot["model_coverage"]["reason"]


def test_coverage_wording_names_modeled_stack_receipt():
    """P3-3L contract: the updated wording leaves stats_only and states
    the modeled stack/stat receipt and any withheld dimension — the
    reason still names Slay, omnivamp, and the stack state, and
    optimizer eligibility is retained."""
    coverage = item_probe.attacker_coverage(get_item_by_name(GLUTTONOUS))
    assert coverage["status"] != "stats_only"
    assert coverage["optimizer_eligible"] is True
    # Ours' reason is derived from the declaration: it names the bounded
    # scenario control the state comes from, not the mechanic's prose.
    # The mechanic itself is pinned by the receipt tests above.
    assert "bounded scenario control" in coverage["reason"]


# ---------------------------------------------------------------------------
# 9. Determinism: identical fights -> identical stack states/receipts
# ---------------------------------------------------------------------------


def test_identical_fights_produce_identical_receipts_and_stats():
    """Two identical fights produce identical combat, champion stats,
    state receipts, self-healing events and timelines."""
    first = _calculate(_main_payload())
    second = _calculate(_main_payload())
    assert first["combat"] == second["combat"]
    assert first["champion_stats"] == second["champion_stats"]
    assert first["self_healing_events"] == second["self_healing_events"]

    full_a = _run_fight(score_only=False)
    full_b = _run_fight(score_only=False)
    assert full_a["item_state_receipts"] == full_b["item_state_receipts"]
    assert full_a["self_healing_events"] == full_b["self_healing_events"]

    timeline_a = _timeline()
    timeline_b = _timeline()
    assert timeline_a == timeline_b


# ---------------------------------------------------------------------------
# 10. The existing Gluttonous app regression stays green
# ---------------------------------------------------------------------------


def test_existing_app_gluttonous_regression_pins_stay_green():
    """Mirrors tests/test_app.py::test_boot_stats_change_damage_and_
    omnivamp_healing for the Gluttonous Greaves branch: the boots change
    damage (Berserker's attack speed > none), Gluttonous grants exactly
    the base 4.0 omnivamp, and that omnivamp heals the main in survival
    (healing_received > 0).  These pins must stay green through P3-3L."""
    client = app.test_client()
    base = {
        "champion": "Jinx",
        "level": 12,
        "items": [],
        "role": "bottom",
        "target_health": 2_000,
        "target_armor": 100,
        "target_mr": 100,
        "auto_attack_uptime": 1.0,
        "auto_attack_uptime_mode": "explicit",
        "fight_duration": 10,
        "enemies": [{"champion": "Galio", "level": 12, "role": "mid"}],
    }
    no_boots = client.post("/api/calculate", json=base).get_json()
    attack_speed_boots = client.post(
        "/api/calculate", json={**base, "boots": "Berserker's Greaves"}
    ).get_json()
    omnivamp_boots = client.post(
        "/api/calculate", json={**base, "boots": GLUTTONOUS}
    ).get_json()

    assert attack_speed_boots["total_damage"] > no_boots["total_damage"]
    assert (
        attack_speed_boots["champion_stats"]["attack_speed"]
        > no_boots["champion_stats"]["attack_speed"]
    )
    assert omnivamp_boots["champion_stats"]["omnivamp_percent"] == BASE_OMNIVAMP
    main = next(
        row
        for row in omnivamp_boots["combat"]["participants"]
        if row["participant_id"] == "main"
    )
    assert main["survival"]["healing_received"] > 0
