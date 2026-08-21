"""P1 Package 3F — Zhonya's Hourglass Time Stop active-stasis acceptance matrix.

Contract under test (binding for the coordinator's P3-3F integration):

* Typed values: ``stasis_duration`` 2.5 through ``required_effect_value``;
  ``ITEM_INPUT_OPTIONS["Zhonya's Hourglass"].stasis_active_seconds`` is a
  float option in [0.0, 2.5] with step 0.5, default 0.0, label
  "Time Stop active seconds"; the option block carries source_url
  https://wiki.leagueoflegends.com/en-us/Zhonya's_Hourglass and
  source_revision_id 3902922.  Missing typed keys raise a KeyError that
  names both the item and the key.
* Input validation: 0 -> no stasis; 2.5 -> exactly 2.5s; 0.5/1.0/2.0 ->
  proportional; values above 2.5 are REJECTED (ValueError "must be between
  0.0 and 2.5" at the request schema layer and at the defensive resolver),
  negatives rejected the same way, nan/inf rejected ("must be finite"),
  non-numeric rejected ("must be numeric").  There is no clamp path today.
* Item presence alone never assumes activation: Zhonya without the option
  yields starting_stasis_duration 0.0, no stasis interval, no stasis
  source; the coverage note pins the "item presence alone never assumes
  stasis" wording.
* Stasis interval + action downtime: stasis_active_seconds 2.0 ->
  survival row stasis_until 2.0, stasis_started_at 0.0, stasis_source
  "Zhonya's Hourglass — Time Stop", action_downtime >= 2.0 with exactly
  one stasis interval row [0.0, 2.0]; incoming damage at t < 2.0 blocked
  (target_state_blocked, 0 health damage) and the first at/after 2.0
  lands; holder outgoing damage at t < 2.0 blocked (attacker_state_blocked).
* Same-time ordering: incoming at exactly t=0 loses to the fight-start
  stasis window (blocked); holder outgoing at t=0 is blocked; the stasis
  expiry at exactly t=2.0 is EXCLUSIVE — a damage packet at exactly 2.0
  lands (pinned at the shared survival-kernel altitude through
  ``_simulate_survival``, the same seam the P2 matrix suites use).
* Source/atom receipts: the starting-defenses source receipt carries the
  label "Zhonya's Hourglass / Seeker's Armguard — Time Stop" and wiki
  revision 3902922; the public survival row exposes
  stasis_until/stasis_started_at/stasis_source and the downtime interval;
  item 3157's atom catalog contains a control.stasis atom (values [2.5],
  hash pinned).
* Score/receipt parity: the compiled walk deep-equals the receipt walk for
  a 2.0s stasis fight on both sides of the fight (Zhonya on the main and
  on the enemy target); ``run_fight`` score-only totals match the full
  receipt.
* Optimizer/BIS/coverage: Zhonya is not optimizer-blocked by stasis
  (optimizer_eligible True, "Time Stop is defensive stasis." registry
  entry, "stasis" in outcome_dimensions); it is not target-blocked
  (target coverage "modeled"); BIS has no stale Zhonya entry.
* Determinism: identical fights produce identical stasis receipts; no
  duplicate stasis packets (exactly one interval row).
* Named boundaries: the input is a fight-start window — no activation
  timestamp option exists and the input alone never authors a stasis
  packet at a nonzero time; the 120s item cooldown is NOT modeled (no
  cooldown key on either registry entry).  Bard R (Temporal Exception) is
  champion-authored and deliberately out of scope here.

All asserted numbers are the typed accessors' expected values (per
AGENTS.md rule 5 tests may assert literals; source must not).
"""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import (
    resolve_starting_defenses,
)
from src.calculator.item_coverage import (
    item_model_coverage,
    target_item_model_coverage,
)
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    required_effect_value,
)
from src.calculator.optimizer import get_eligible_legendaries
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    _simulate_survival as _simulate_survival_walk,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

# The retired per-item ``_X_SOURCE`` constant, read from the one home it
# moved to: the declaration's own resolved citation.
from src.calculator.defensive_effects import defense_source
from src.calculator.item_behavior import DefenseMechanic

from src.calculator.item_coverage import ATTACKER_LANES


# MERGE: ``_simulate_survival`` returns the frozen ``WalkResult`` now -- one
# walk handed to five views -- so a caller that wants the published rows
# projects it through the survival view, exactly as the composition does.
def _simulate_survival(combatants, *args, **kwargs):
    combatant_list = list(combatants)
    return _survival_view(
        _roster_program(combatant_list),
        _simulate_survival_walk(combatant_list, *args, **kwargs),
    )


def _attacker_coverage(item):
    """Ours' lane-taking classifier, called with the cached record these
    tests carry.  The payload shape is unchanged; only the argument moved
    from the record to the name plus the lanes the caller needs."""
    return item_model_coverage(str(item["name"]), ATTACKER_LANES).as_payload()


_SOURCE = defense_source("Zhonya's Hourglass", DefenseMechanic.TIME_STOP)

ZHONYA = "Zhonya's Hourglass"
STASIS_SOURCE_LABEL = "Zhonya's Hourglass — Time Stop"
REVISION_ID = 3902922
ATOMS_PATH = Path(__file__).resolve().parent.parent / "data" / "atoms" / "items.json"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _params(**overrides):
    """A deterministic time-based fight request with Zhonya's option."""
    base = {
        "fight_mode": "time_based",
        "fight_duration": 12,
        "role": "mid",
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        # E:0 keeps the enemy out of Ahri's charm so stasis blocking is the
        # only pre-2.0 damage gate (deterministic boundary fixture).
        "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
    }
    base.update(overrides)
    return FightParams.from_request(base, deterministic=True)


def _roster(champion, level=18, items=(), role="mid", item_options=None):
    return ChampionLoadout(
        champion=champion,
        level=level,
        role=role,
        items=items,
        item_options=item_options or {},
    ).resolve()


def _timeline(
    champion_name,
    level,
    items,
    params,
    enemies,
    *,
    role="mid",
    **kwargs,
):
    champion = get_champion(champion_name)
    stats = calculate_total_stats(champion, level, items, role=role)
    # Production seam mirror (src/calculator/calculate.py:_combat_receipt):
    # item options are wired into the starting defenses.
    defenses = resolve_starting_defenses(
        champion_name, level, stats, items, item_options=params.item_options
    )
    return build_participant_timeline(
        champion,
        level,
        items,
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=list(enemies),
        allies=[],
        **kwargs,
    )


def _zhonya_defenses(item_options=None, champion="Ahri"):
    """Resolve one Zhonya build's starting defenses (option-aware)."""
    zhonya = get_item_by_name(ZHONYA)
    stats = calculate_total_stats(get_champion(champion), 18, [zhonya], role="mid")
    return resolve_starting_defenses(
        champion, 18, stats, [zhonya], item_options=item_options
    )


def _stasis_fight(seconds=2.0, duration=8.0, champion="Ahri"):
    """The canonical clean stasis fight: Zhonya holder vs Janna, no charm."""
    zhonya = get_item_by_name(ZHONYA)
    params = _params(
        fight_duration=duration,
        item_options={ZHONYA: {"stasis_active_seconds": seconds}},
    )
    return _timeline(champion, 18, [zhonya], params, [_roster("Janna")])


def _no_option_fight(duration=8.0, champion="Ahri"):
    zhonya = get_item_by_name(ZHONYA)
    params = _params(fight_duration=duration)
    return _timeline(champion, 18, [zhonya], params, [_roster("Janna")])


def _survival(result, participant_id="main"):
    return next(
        row["survival"]
        for row in result["participants"]
        if row["participant_id"] == participant_id
    )


def _events(result, attacker=None, target=None):
    return [
        event
        for event in result["events"]
        if (attacker is None or event.get("attacker") == attacker)
        and (target is None or event.get("target") == target)
    ]


# ---------------------------------------------------------------------------
# 1. Typed accessor values + option schema + missing-key fail-closed
# ---------------------------------------------------------------------------


def test_typed_stasis_duration_and_option_schema():
    """stasis_duration is 2.5 through the typed accessor; the public input
    option is a float in [0, 2.5] with step 0.5, default 0.0."""
    assert required_effect_value(ZHONYA, "stasis_duration") == 2.5
    option = ITEM_INPUT_OPTIONS[ZHONYA]["options"]["stasis_active_seconds"]
    assert option == {
        "type": "float",
        "label": "Time Stop active seconds",
        "default": 0.0,
        "min": 0.0,
        "max": 2.5,
        "step": 0.5,
    }


def test_option_block_carries_wiki_source_and_revision():
    """The option registry names the wiki page and revision 3902922."""
    block = ITEM_INPUT_OPTIONS[ZHONYA]
    assert (
        block["source_url"]
        == "https://wiki.leagueoflegends.com/en-us/Zhonya's_Hourglass"
    )
    assert block["source_revision_id"] == REVISION_ID


def test_missing_stasis_key_raises_keyerror_naming_item_and_key(monkeypatch):
    """A missing typed key fails loud, naming the item and the key."""
    # Deleted from the live entry rather than swapped for a copy: the
    # declaration holds a reference into the registry and resolves it at read
    # time, so rebinding the name would leave the compiled rule pointing at
    # the intact mapping and prove nothing.
    monkeypatch.delitem(ITEM_EFFECTS[ZHONYA], "stasis_duration")

    with pytest.raises(KeyError) as excinfo:
        _zhonya_defenses(item_options={ZHONYA: {"stasis_active_seconds": 2.0}})
    message = str(excinfo.value)
    # str(KeyError) wraps the repr, escaping the apostrophe; the item and
    # key names still appear verbatim.
    assert "Zhonya" in message and "Hourglass" in message
    assert "stasis_duration" in message


# ---------------------------------------------------------------------------
# 2. Input validation matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [0.0, 0.5, 1.0, 2.0, 2.5])
def test_activation_seconds_map_proportionally(seconds):
    """0 -> no stasis; 0.5/1.0/2.0 -> proportional; 2.5 -> exactly 2.5."""
    defenses = _zhonya_defenses(
        item_options={ZHONYA: {"stasis_active_seconds": seconds}}
    )
    assert defenses.starting_stasis_duration == pytest.approx(seconds)
    if seconds > 0.0:
        assert defenses.starting_stasis_source == STASIS_SOURCE_LABEL
        assert any("explicitly active" in note for note in defenses.assumptions)
        assert any(
            "never assumed active by item presence alone" in note
            for note in defenses.assumptions
        )
    else:
        assert defenses.starting_stasis_source == ""
        assert not any("Time Stop" in note for note in defenses.assumptions)


@pytest.mark.parametrize("seconds", [2.5001, 3.0, 10.0])
def test_validation_rejects_values_above_max(seconds):
    """Above 2.5 the schema layer raises; there is no clamp path today."""
    with pytest.raises(
        ValueError, match=r"stasis_active_seconds must be between 0.0 and 2.5"
    ):
        _params(item_options={ZHONYA: {"stasis_active_seconds": seconds}})
    with pytest.raises(
        ValueError, match=r"stasis_active_seconds must be between 0.0 and 2.5"
    ):
        _zhonya_defenses(item_options={ZHONYA: {"stasis_active_seconds": seconds}})


@pytest.mark.parametrize("seconds", [-0.5, -1.0, -2.5])
def test_validation_rejects_negative_values(seconds):
    with pytest.raises(
        ValueError, match=r"stasis_active_seconds must be between 0.0 and 2.5"
    ):
        _params(item_options={ZHONYA: {"stasis_active_seconds": seconds}})
    with pytest.raises(
        ValueError, match=r"stasis_active_seconds must be between 0.0 and 2.5"
    ):
        _zhonya_defenses(item_options={ZHONYA: {"stasis_active_seconds": seconds}})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (float("nan"), "must be finite"),
        (float("inf"), "must be finite"),
        (float("-inf"), "must be finite"),
        (True, "must be numeric"),
        (None, "must be numeric"),
    ],
)
def test_validation_rejects_non_finite_and_non_numeric(value, message):
    with pytest.raises(ValueError, match=message):
        _params(item_options={ZHONYA: {"stasis_active_seconds": value}})
    with pytest.raises(ValueError, match=message):
        _zhonya_defenses(item_options={ZHONYA: {"stasis_active_seconds": value}})


def test_numeric_strings_are_accepted_and_coerced():
    """A numeric string "2.5" is coerced by both layers (not rejected)."""
    params = _params(item_options={ZHONYA: {"stasis_active_seconds": "2.5"}})
    assert params.item_options[ZHONYA]["stasis_active_seconds"] == 2.5
    defenses = _zhonya_defenses(item_options={ZHONYA: {"stasis_active_seconds": "2.5"}})
    assert defenses.starting_stasis_duration == pytest.approx(2.5)


def test_unknown_option_name_rejected_at_request_layer():
    """The request schema rejects unknown option names; the resolver treats
    a missing known option as 0.0 (fail-closed no activation)."""
    with pytest.raises(
        ValueError, match=r"Unknown option for Zhonya's Hourglass: stasis_start_time"
    ):
        _params(item_options={ZHONYA: {"stasis_start_time": 1.0}})
    defenses = _zhonya_defenses(item_options={ZHONYA: {"stasis_start_time": 1.0}})
    assert defenses.starting_stasis_duration == 0.0
    assert defenses.starting_stasis_source == ""


# ---------------------------------------------------------------------------
# 3. Item presence alone never assumes activation
# ---------------------------------------------------------------------------


def test_item_presence_alone_never_activates_stasis():
    """Zhonya with NO option: no stasis interval, no stasis source, and the
    coverage reason pins the 'item presence alone' assumption wording."""
    defenses = _zhonya_defenses()
    assert defenses.starting_stasis_duration == 0.0
    assert defenses.starting_stasis_source == ""

    result = _no_option_fight()
    survival = _survival(result)
    assert survival["stasis_until"] == 0.0
    assert survival["stasis_started_at"] is None
    assert survival["stasis_source"] == ""
    assert survival["action_downtime"] == 0.0
    assert survival["action_downtime_intervals"] == []

    # The gate sentence is the ATTACKER lane's receipt: it is the answer to
    # "can the pair engine price this?", and the gate is why the answer does
    # not depend on holding the item.  The target lane answers a different
    # question (what the wearer survives) and names the mechanic instead.
    assert "Time Stop" in target_item_model_coverage(get_item_by_name(ZHONYA))["reason"]
    for coverage in (_attacker_coverage(get_item_by_name(ZHONYA)),):
        assert (
            "Time Stop is priced only from the explicit bounded active-seconds "
            "scenario input; item presence alone never assumes stasis."
            in coverage["reason"]
        )


# ---------------------------------------------------------------------------
# 4. Stasis interval, action downtime, damage blocking
# ---------------------------------------------------------------------------


def test_stasis_interval_and_action_downtime_receipt():
    """2.0s input -> stasis_until 2.0 at 0, named source, downtime >= 2.0
    with exactly one [0, 2.0] interval row."""
    result = _stasis_fight(seconds=2.0)
    survival = _survival(result)
    assert survival["stasis_until"] == pytest.approx(2.0)
    assert survival["stasis_started_at"] == pytest.approx(0.0)
    assert survival["stasis_source"] == STASIS_SOURCE_LABEL
    assert survival["action_downtime"] >= 2.0 - 1e-9
    assert survival["action_downtime_intervals"] == [
        {
            "recipient": "main",
            "kind": "stasis",
            "start": 0.0,
            "end": 2.0,
            "source": STASIS_SOURCE_LABEL,
        }
    ]


def test_incoming_damage_blocked_during_stasis_and_lands_after():
    """Every enemy packet at t < 2.0 is blocked with zero applied damage;
    the first at/after 2.0 lands, and the blocked sum is exactly the
    damage delta vs the no-option fight."""
    stasis = _stasis_fight(seconds=2.0)
    plain = _no_option_fight()
    blocked = [
        event for event in _events(plain, attacker="enemy:Janna") if event["time"] < 2.0
    ]
    assert blocked
    for event in blocked:
        assert event["damage"] > 0.0  # these land without stasis
    blocked_sum = sum(event["damage"] for event in blocked)

    stasis_enemy_events = _events(stasis, attacker="enemy:Janna")
    for event in stasis_enemy_events:
        if event["time"] < 2.0:
            assert event["skipped_reason"] == "target_state_blocked"
            assert event["damage"] == 0.0
    landed = [event for event in stasis_enemy_events if event["time"] >= 2.0]
    assert landed
    assert all(event.get("skipped_reason") is None for event in landed)
    assert landed[0]["time"] == pytest.approx(2.119)

    assert _survival(stasis)["damage_taken"] == pytest.approx(301.1)
    assert _survival(plain)["damage_taken"] == pytest.approx(301.1 + blocked_sum)


def test_holder_outgoing_actions_blocked_during_stasis():
    """The Zhonya holder's autos/casts at t < 2.0 deal no damage
    (attacker_state_blocked); the first post-stasis action lands."""
    stasis = _stasis_fight(seconds=2.0)
    plain = _no_option_fight()

    blocked_holder_events = [
        event
        for event in _events(stasis, attacker="main")
        if event["time"] < 2.0 and event["damage_type"] in {"physical", "magic", "true"}
    ]
    assert blocked_holder_events
    for event in blocked_holder_events:
        assert event["skipped_reason"] == "attacker_state_blocked"
        assert event["damage"] == 0.0
    # the same pre-2.0 holder packets deal damage without stasis
    plain_holder = {
        (event["time"], event.get("source"), event.get("damage_type")): event["damage"]
        for event in _events(plain, attacker="main")
        if event["time"] < 2.0
    }
    assert any(
        plain_holder.get(
            (event["time"], event.get("source"), event.get("damage_type")), 0.0
        )
        > 0.0
        for event in blocked_holder_events
    )
    landed = [
        event for event in _events(stasis, attacker="main") if event["time"] >= 2.0
    ]
    assert landed and any(event["damage"] > 0.0 for event in landed)


# ---------------------------------------------------------------------------
# 5. Same-time ordering (shared survival-kernel altitude, exact times)
# ---------------------------------------------------------------------------


def _kernel_combatant(participant_id, team, stasis=0.0, health=5000.0):
    defenses = StartingDefenses(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.0,
        starting_stasis_duration=stasis,
        starting_stasis_source=STASIS_SOURCE_LABEL if stasis > 0.0 else "",
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=18,
        items=(),
        stats={
            "health": health,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "base_health": 2000.0,
            "is_melee": False,
        },
        defenses=defenses,
    )


def _kernel_packet(time, amount, attacker, target, source="Q", sequence=0):
    return {
        "time": time,
        "damage": amount,
        "damage_type": "magic",
        "attacker": attacker,
        "target": target,
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "damage",
        "sequence": sequence,
        "_event_id": f"dmg-{sequence}-{time}-{source}",
    }


def test_same_time_ordering_stasis_wins_and_expiry_is_exclusive():
    """At t=0 stasis beats both incoming damage and the holder's own
    outgoing actions; a packet at exactly t=2.0 (the expiry) lands —
    the window is [0, 2.0) exclusive of the end."""
    combatants = [
        _kernel_combatant("main", "blue", stasis=2.0),
        _kernel_combatant("enemy", "red"),
    ]
    incoming = {
        "main": [
            _kernel_packet(0.0, 500.0, "enemy", "main", source="Q0"),
            _kernel_packet(1.0, 500.0, "enemy", "main", source="Q1"),
            _kernel_packet(2.0, 500.0, "enemy", "main", source="Q2"),
            _kernel_packet(2.5, 500.0, "enemy", "main", source="Q3"),
        ],
        "enemy": [
            _kernel_packet(0.0, 300.0, "main", "enemy", source="auto_attacks"),
            _kernel_packet(1.0, 300.0, "main", "enemy", source="Q1"),
            _kernel_packet(2.0, 300.0, "main", "enemy", source="Q2"),
        ],
    }
    result = _simulate_survival(combatants, incoming, {}, {}, 6.0)

    main = result["main"]
    assert main["health_damage"] == pytest.approx(1000.0)  # t=0,1 blocked; t=2,2.5 land
    assert main["stasis_until"] == pytest.approx(2.0)
    assert main["stasis_started_at"] == pytest.approx(0.0)
    assert main["stasis_source"] == STASIS_SOURCE_LABEL
    assert main["action_downtime"] == pytest.approx(2.0)
    assert main["action_downtime_intervals"] == [
        {
            "recipient": "main",
            "kind": "stasis",
            "start": 0.0,
            "end": 2.0,
            "source": STASIS_SOURCE_LABEL,
        }
    ]
    # holder outgoing: t=0 and t=1.0 blocked, t=2.0 lands
    assert result["enemy"]["health_damage"] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# 6. Source/atom receipts
# ---------------------------------------------------------------------------


def test_stasis_source_receipt_carries_label_and_wiki_revision():
    """The active stasis receipts carry the Time Stop label and the pinned
    wiki revision on both the typed source and the public summary."""
    assert _SOURCE.label == "Zhonya's Hourglass / Seeker's Armguard — Time Stop"
    assert _SOURCE.revision_id == REVISION_ID

    defenses = _zhonya_defenses(item_options={ZHONYA: {"stasis_active_seconds": 2.0}})
    summary = defenses.public_summary()
    assert summary["combat_state"]["starting_stasis"] == {
        "duration": 2.0,
        "source": STASIS_SOURCE_LABEL,
    }
    assert summary["sources"] == [
        {
            "label": "Zhonya's Hourglass / Seeker's Armguard — Time Stop",
            "url": "https://wiki.leagueoflegends.com/en-us/Zhonya%27s_Hourglass",
            "revision_id": REVISION_ID,
            "revision_timestamp": "2025-05-29T13:29:45Z",
        }
    ]
    # the option registry spells the same page with a literal apostrophe
    assert ITEM_INPUT_OPTIONS[ZHONYA]["source_url"].endswith("Zhonya's_Hourglass")


def test_stasis_atom_exists_in_item_3157_catalog():
    """data/atoms/items.json item 3157 carries the Time Stop control atom."""
    assert get_item_by_name(ZHONYA)["id"] == 3157
    atoms = json.loads(ATOMS_PATH.read_text(encoding="utf-8"))
    entries = atoms["objects"].get("3157")
    assert entries is not None
    stasis_atoms = [entry for entry in entries if entry["atom_id"] == "control.stasis"]
    assert stasis_atoms == [
        {
            "atom_id": "control.stasis",
            "behavior": "control",
            "source": "Zhonya's Hourglass.actives[0].branches[0]",
            "name": "Time Stop",
            "values": [2.5],
            "units": ["flat"],
            "evidence": ["active:Time Stop@kw:stasis"],
            "hash": "48781f08a515df76",
        }
    ]


# ---------------------------------------------------------------------------
# 7. Score/receipt parity (compiled walk and score-only fight)
# ---------------------------------------------------------------------------


def _assert_compiled_parity(
    name, champion_name, items, params, enemies, role="mid", stasis_participant="main"
):
    legacy = _timeline(
        champion_name,
        18,
        items,
        params,
        enemies,
        role=role,
        include_receipt=False,
    )
    context = CoupledSearchContext()
    fast = _timeline(
        champion_name,
        18,
        items,
        params,
        enemies,
        role=role,
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    assert fast == legacy, f"{name}: compiled walk diverged from the receipt walk"
    assert context.uncompilable is False, f"{name}: expected compiled path usable"
    assert context.panels, f"{name}: expected the compiled panel to be used"
    # Guard against a weak pin (test_survival_kernel.py:314's helper never
    # wires item_options into defenses, so its "stasis" parity runs with no
    # active stasis): here the receipt walk must carry the real stasis.
    stasis_row = next(
        row
        for row in legacy["participants"]
        if row["participant_id"] == stasis_participant
    )
    assert stasis_row["survival"]["stasis_until"] == pytest.approx(2.0)
    assert any(
        row["kind"] == "stasis" and row["start"] == 0.0 and row["end"] == 2.0
        for row in stasis_row["survival"]["action_downtime_intervals"]
    )


def test_compiled_walk_equals_receipt_walk_main_side_zhonya():
    """Zhonya stasis on the HOLDER rides the compiled walk (mirror of
    test_survival_kernel.py:314 at a different altitude: Zhonya-only build,
    no Infinity Edge, no charm ranks)."""
    params = _params(
        fight_duration=12,
        item_options={ZHONYA: {"stasis_active_seconds": 2.0}},
    )
    _assert_compiled_parity(
        "zhonya-main",
        "Ahri",
        [get_item_by_name(ZHONYA)],
        params,
        [_roster("Janna")],
    )


def test_compiled_walk_equals_receipt_walk_target_side_zhonya():
    """Zhonya stasis on the ENEMY target also rides the compiled walk: the
    target's stasis window gates the attacker's packets identically."""
    params = _params(
        fight_duration=9,
        include_auto_attacks=False,
        ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
        item_options={ZHONYA: {"stasis_active_seconds": 2.0}},
    )
    _assert_compiled_parity(
        "zhonya-target",
        "Ezreal",
        [],
        params,
        [
            _roster(
                "Ahri",
                items=(ZHONYA,),
                item_options={ZHONYA: {"stasis_active_seconds": 2.0}},
            )
        ],
        stasis_participant="enemy:Ahri",
    )


def test_score_only_fight_parity_zhonya_build():
    """run_fight score_only keeps every scoring field identical for a
    Zhonya build (totals and per-event scoring projections)."""
    zhonya = get_item_by_name(ZHONYA)
    params = _params(item_options={ZHONYA: {"stasis_active_seconds": 2.0}})
    full = run_fight(get_champion("Ahri"), 18, [zhonya], params, score_only=False)
    score = run_fight(get_champion("Ahri"), 18, [zhonya], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    scoring_keys = ("time", "source_key", "damage_type", "raw_damage", "damage")
    assert [
        tuple(event.get(key) for key in scoring_keys)
        for event in score["damage_events"]
    ] == [
        tuple(event.get(key) for key in scoring_keys) for event in full["damage_events"]
    ]
    assert score["resource_spent"] == full["resource_spent"]


# ---------------------------------------------------------------------------
# 8. Optimizer / BIS / coverage
# ---------------------------------------------------------------------------


def test_zhonya_not_optimizer_blocked_by_stasis():
    """Zhonya stays optimizer-eligible with stasis as a reviewed outcome
    dimension; the registry entry names Time Stop as defensive stasis."""
    coverage = _attacker_coverage(get_item_by_name(ZHONYA))
    assert coverage["optimizer_eligible"] is True
    assert coverage["status"] == "stats_only"
    assert coverage["calculation_eligible"] is True
    assert "stasis" in coverage["outcome_dimensions"]
    # The reviewed sentence is derived from the declaration's own bounded
    # gate now, not typed into a per-item table.
    assert "Time Stop" in coverage["reason"]
    assert get_item_by_name(ZHONYA)["name"] in {
        item["name"] for item in get_eligible_legendaries()
    }


def test_stasis_dimension_not_target_blocked_and_no_stale_bis_entry():
    """Zhonya is target-modeled (not in the target-blocked reasons) and BIS
    carries no stale Zhonya entry."""
    target = target_item_model_coverage(get_item_by_name(ZHONYA))
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True
    assert "stasis" in target["outcome_dimensions"]
    # "not target-blocked" is the derived status itself now: the retired
    # per-item refusal table is gone, and a refusal would show up here.
    assert target["status"] not in {"withheld", "review_pending"}

    bis_source = (
        Path(__file__).resolve().parent.parent / "src" / "calculator" / "bis.py"
    ).read_text(encoding="utf-8")
    assert "Zhonya" not in bis_source


# ---------------------------------------------------------------------------
# 9. Determinism
# ---------------------------------------------------------------------------


def test_identical_fights_produce_identical_stasis_receipts():
    """Two identical stasis fights deep-equal, and no duplicate stasis
    packets are emitted."""
    first = _stasis_fight(seconds=2.0)
    second = _stasis_fight(seconds=2.0)
    assert first == second
    survival = _survival(first)
    assert survival["stasis_until"] == pytest.approx(2.0)
    assert len(survival["action_downtime_intervals"]) == 1
    assert [
        row for row in survival["action_downtime_intervals"] if row["kind"] == "stasis"
    ] == survival["action_downtime_intervals"]


# ---------------------------------------------------------------------------
# 10. Named boundaries: fight-start window only, no cooldown modeled
# ---------------------------------------------------------------------------


def test_input_never_authors_midfight_stasis_packet():
    """The option is a fight-start window: the only stasis artifact it
    authors starts at t=0, and no activation-timestamp option exists."""
    result = _stasis_fight(seconds=2.0)
    survival = _survival(result)
    assert survival["stasis_started_at"] == pytest.approx(0.0)
    assert all(row["start"] == 0.0 for row in survival["action_downtime_intervals"])
    assert all(row["kind"] == "stasis" for row in survival["action_downtime_intervals"])
    assert set(ITEM_INPUT_OPTIONS[ZHONYA]["options"]) == {"stasis_active_seconds"}
    assert all(
        "start_time" not in key and "time" not in key
        for key in ITEM_INPUT_OPTIONS[ZHONYA]["options"]
    )


def test_zhonya_cooldown_is_not_modeled():
    """The 120s item cooldown has no key on either registry entry."""
    # P3-3F: the registry record also carries the code-owned wiki revision
    # receipt (page 43052, rev 3902922) as static keys; the stasis value
    # itself stays the only numeric key.
    assert set(ITEM_EFFECTS[ZHONYA]) == {
        "type",
        "stasis_duration",
        "source_url",
        "source_revision_id",
    }
    assert ITEM_EFFECTS[ZHONYA]["source_url"] == (
        "https://wiki.leagueoflegends.com/en-us/Zhonya's_Hourglass"
    )
    assert ITEM_EFFECTS[ZHONYA]["source_revision_id"] == 3902922
    assert set(ITEM_INPUT_OPTIONS[ZHONYA]) == {
        "options",
        "source_url",
        "source_revision_id",
    }
    assert "cooldown" not in ITEM_EFFECTS[ZHONYA]
    assert "cooldown" not in ITEM_INPUT_OPTIONS[ZHONYA]


def test_step_validation_rejects_non_multiple_values():
    """P3-3F: stasis_active_seconds is bounded, finite, AND a step multiple
    (0.5) at both the request layer and the resolver layer — a value like
    1.3 or 2.25 is rejected, not silently rounded."""
    from src.calculator.pipeline import FightParams

    for bad in (1.3, 2.25, 0.7):
        with pytest.raises(ValueError, match="multiple of 0.5"):
            FightParams.from_request(
                {
                    "fight_mode": "one_rotation",
                    "item_options": {ZHONYA: {"stasis_active_seconds": bad}},
                },
                deterministic=True,
            )
        with pytest.raises(ValueError, match="multiple of 0.5"):
            _zhonya_defenses(item_options={ZHONYA: {"stasis_active_seconds": bad}})
    # Multiples still pass through both layers.
    for good in (0.0, 0.5, 1.0, 2.0, 2.5):
        defenses = _zhonya_defenses(
            item_options={ZHONYA: {"stasis_active_seconds": good}}
        )
        assert defenses.starting_stasis_duration == pytest.approx(good)
