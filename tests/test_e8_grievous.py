"""E8b: Grievous Wounds application and Serpent's Fang shield-reduction.

Covers four sourced mechanics end to end:

1. ITEM Grievous Wounds — the coupled survival walk reduces a target's
   self-healing by the patch-wide 40% (factor 0.60) for 3 seconds after a
   qualifying hit from an item such as Morellonomicon or Oblivion Orb.
2. CHAMPION Grievous Wounds — Katarina R (Death Lotus) and Varus E (Hail
   of Arrows) wound the enemy they damage: the same 40%-for-3s window,
   refreshed by every Death Lotus dagger, sourced to the ability label.
3. Serpent's Fang venom — shields the target gains while the venom window
   is active are cut by the sourced melee/ranged fraction (50%/35%) at
   shield-grant time.
4. The four anti-heal items through the public payload boundary — each one
   bites only on its own trigger damage type, and the compiled search walk
   the optimizer runs prices the wound identically to the receipt walk.

No number in this file is invented: the wound strength/duration are the
engine's ``GRIEVOUS_WOUNDS_FACTOR``/``GRIEVOUS_WOUNDS_DURATION`` constants
and the venom values come from the ``item_effects`` typed accessors.
"""

from dataclasses import replace

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.healing_reduction import (
    GRIEVOUS_WOUNDS_DURATION,
    GRIEVOUS_WOUNDS_FACTOR,
    champion_grievous_wound_sources,
    healing_reduction_profiles,
)
from src.calculator.survival import resolve_grievous
from src.calculator.item_effects import serpents_fang_venom
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    _simulate_survival,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")


def _simulated_rows(combatants, *args, **kwargs):
    """The published survival rows for one simulated walk.

    ``_simulate_survival`` returns the frozen walk result from S9 on, because
    the composition hands that one result to five views.  These tests read the
    published rows, so they project it through the survival view exactly as
    the composition does.
    """
    return _survival_view(
        _roster_program(combatants),
        _simulate_survival(combatants, *args, **kwargs),
    )


def _dummy_combatant(
    participant_id: str,
    team: str,
    *,
    health: float = 100.0,
    items=(),
    is_melee: bool = True,
) -> Combatant:
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
        items=tuple(items),
        stats={"health": health, "is_melee": is_melee},
        defenses=defenses,
    )


def _build(main_champion, level, items, params, enemies, allies=()):
    """Run the coupled timeline for a main loadout against a roster."""
    stats = calculate_total_stats(main_champion, level, items)
    defenses = resolve_starting_defenses(
        main_champion.get("name", ""), level, stats, items
    )
    return build_participant_timeline(
        main_champion,
        level,
        items,
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=list(enemies),
        allies=list(allies),
    )


def _aatrox_self_healer() -> ChampionLoadout:
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=[]).resolve()
    enemy_stats = dict(enemy.stats)
    enemy_stats.update(health=5000.0, armor=0.0, magic_resistance=0.0)
    return replace(enemy, stats=enemy_stats)


# ---------------------------------------------------------------------------
# 1) ITEM Grievous Wounds, end to end
# ---------------------------------------------------------------------------


def test_item_grievous_wounds_morellonomicon_reduces_self_healing():
    """Annie holding Morellonomicon wounds Aatrox's heals for 3 seconds."""
    main = get_champion("Aatrox")
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "ability_ranks": {"Q": 5, "W": 3, "E": 5, "R": 2},
            "auto_attack_uptime": 0.5,
        },
        deterministic=True,
    )
    baseline = _build(main, 18, [], params, [_aatrox_self_healer()])
    wounded = _build(
        main,
        18,
        [],
        params,
        [
            ChampionLoadout(
                champion="Annie", level=18, items=["Morellonomicon"]
            ).resolve()
        ],
    )
    baseline_survival = baseline["participants"][0]["survival"]
    wounded_survival = wounded["participants"][0]["survival"]

    assert baseline_survival["healing_reduced"] == 0.0
    assert wounded_survival["healing_reduced"] > 0.0
    assert wounded_survival["healing_received"] < baseline_survival["healing_received"]

    # Every heal inside the wound window is reduced by exactly the patch
    # factor (40% cut), and the source label names the item.
    in_window = [
        event
        for event in wounded["healing_events"]
        if event.get("attacker") == "main"
        and event.get("healing_reduction_factor")
        == pytest.approx(GRIEVOUS_WOUNDS_FACTOR)
    ]
    assert in_window
    for event in in_window:
        assert event["applied_amount"] == pytest.approx(
            event["raw_amount"] * GRIEVOUS_WOUNDS_FACTOR, abs=0.1
        )
    assert wounded_survival["healing_reduction_sources"] == [
        "Morellonomicon · Grievous Wounds"
    ]
    assert wounded_survival["healing_reduction_until"] > 0.0


def test_item_grievous_wounds_oblivion_orb_three_second_window_expiry():
    """Oblivion Orb wounds for 3 seconds; healing after expiry is full.

    The unit-level survival walk pins the window arithmetic exactly: a
    damage hit at t=0 reduces the t=1 heal to 60%, and the t=4 heal lands
    after the window expired and is not reduced at all.
    """
    orb = get_item_by_name("Oblivion Orb")
    source = _dummy_combatant("source", "main", items=[orb])
    target = _dummy_combatant("target", "enemy", health=300.0)
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 50.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "wound-hit",
                }
            ]
        },
        {
            "target": [
                {
                    "time": 1.0,
                    "amount": 100.0,
                    "attacker": "target",
                    "source": "in-window heal",
                },
                {
                    "time": 4.0,
                    "amount": 100.0,
                    "attacker": "target",
                    "source": "post-window heal",
                },
            ]
        },
        {},
        10.0,
    )
    assert result["target"]["healing_reduction_until"] == pytest.approx(
        GRIEVOUS_WOUNDS_DURATION
    )
    assert result["target"]["healing_reduction_events"][0]["factor"] == pytest.approx(
        GRIEVOUS_WOUNDS_FACTOR
    )
    # The t=1 heal keeps 60%; the t=4 heal is out of the window and is not
    # reduced at all.  ``healing_reduced`` counts the 40% cut on the raw
    # in-window heal regardless of how much fit in the missing health.
    assert result["target"]["healing_reduction_events"][0]["sources"] == [
        "Oblivion Orb · Grievous Wounds"
    ]
    assert result["target"]["healing_reduced"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# 2) CHAMPION Grievous Wounds
# ---------------------------------------------------------------------------


def test_champion_grievous_wound_sources_resolve_from_modules():
    """Katarina R and Varus E declare sourced wounds; others fail closed."""
    katarina = get_champion("Katarina")
    varus = get_champion("Varus")
    ahri = get_champion("Ahri")

    kat_sources = champion_grievous_wound_sources(katarina)
    var_sources = champion_grievous_wound_sources(varus)

    assert kat_sources == (
        {
            "source_key": "R",
            "source": "Katarina · Death Lotus",
            "factor": GRIEVOUS_WOUNDS_FACTOR,
            "duration": GRIEVOUS_WOUNDS_DURATION,
        },
    )
    assert var_sources == (
        {
            "source_key": "E",
            "source": "Varus · Hail of Arrows",
            "factor": GRIEVOUS_WOUNDS_FACTOR,
            "duration": GRIEVOUS_WOUNDS_DURATION,
        },
    )
    # A champion without a wound declaration must never invent a wound.
    assert champion_grievous_wound_sources(ahri) == ()


def test_katarina_death_lotus_wounds_enemy_self_healer():
    """Every Death Lotus dagger refreshes the 40%-for-3s wound window."""
    main = get_champion("Katarina")
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 6,
            "ability_ranks": {"Q": 1, "W": 1, "E": 1, "R": 1},
            "auto_attack_uptime": 0.0,
        },
        deterministic=True,
    )
    result = _build(main, 18, [], params, [_aatrox_self_healer()])
    enemy_survival = result["participants"][1]["survival"]

    # The wound rides the R damage events, sourced to the ability label.
    r_wounds = [
        event
        for event in result["events"]
        if event.get("wound_source") == "Katarina · Death Lotus"
    ]
    assert r_wounds
    for event in r_wounds:
        assert event["wound_duration"] == pytest.approx(GRIEVOUS_WOUNDS_DURATION)

    # The window is refreshed per dagger: the last dagger at ~2.9s extends
    # the wound past the fixed 3s-from-first-hit mark.
    assert enemy_survival["healing_reduction_until"] > GRIEVOUS_WOUNDS_DURATION
    assert enemy_survival["healing_reduction_events"][0]["factor"] == pytest.approx(
        GRIEVOUS_WOUNDS_FACTOR
    )
    assert "Katarina · Death Lotus" in enemy_survival["healing_reduction_sources"]
    assert enemy_survival["healing_reduced"] > 0.0
    # The heal that lands after the first dagger keeps exactly 60%.
    reduced_heals = [
        event
        for event in result["healing_events"]
        if event.get("attacker") == "enemy:Aatrox"
        and event.get("healing_reduction_factor")
        == pytest.approx(GRIEVOUS_WOUNDS_FACTOR)
    ]
    assert reduced_heals
    for event in reduced_heals:
        assert event["applied_amount"] == pytest.approx(
            event["raw_amount"] * GRIEVOUS_WOUNDS_FACTOR, abs=0.1
        )


def test_varus_hail_of_arrows_wounds_enemy_self_healer():
    """Varus E applies the 40%-for-3s wound to everyone it damages."""
    main = get_champion("Varus")
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 6,
            "ability_ranks": {"Q": 0, "W": 0, "E": 3, "R": 0},
            "champion_options": {"blight_stacks": 0},
            "auto_attack_uptime": 0.0,
        },
        deterministic=True,
    )
    result = _build(main, 18, [], params, [_aatrox_self_healer()])
    enemy_survival = result["participants"][1]["survival"]

    e_wounds = [
        event
        for event in result["events"]
        if event.get("wound_source") == "Varus · Hail of Arrows"
    ]
    assert e_wounds
    assert e_wounds[0]["wound_duration"] == pytest.approx(GRIEVOUS_WOUNDS_DURATION)
    assert enemy_survival["healing_reduction_events"][0]["factor"] == pytest.approx(
        GRIEVOUS_WOUNDS_FACTOR
    )
    assert enemy_survival["healing_reduction_until"] == pytest.approx(
        GRIEVOUS_WOUNDS_DURATION
    )
    assert "Varus · Hail of Arrows" in enemy_survival["healing_reduction_sources"]
    assert enemy_survival["healing_reduced"] > 0.0


def test_champion_wounds_and_venom_compiled_walk_matches_legacy_walk():
    """Katarina R wounds + Serpent's Fang venom agree across both walks."""
    main = get_champion("Katarina")
    items = [get_item_by_name("Serpent's Fang")]
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 6,
            "ability_ranks": {"Q": 1, "W": 1, "E": 1, "R": 1},
            "auto_attack_uptime": 0.0,
        },
        deterministic=True,
    )
    stats = calculate_total_stats(main, 18, items)
    defenses = resolve_starting_defenses("Katarina", 18, stats, items)
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=[]).resolve()
    enemy_stats = dict(enemy.stats)
    enemy_stats.update(health=5000.0, armor=0.0, magic_resistance=0.0)
    enemy = replace(enemy, stats=enemy_stats)

    def timeline(**kwargs):
        return build_participant_timeline(
            main,
            18,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=[enemy],
            allies=[],
            **kwargs,
        )

    legacy = timeline(include_receipt=False)
    fast = timeline(
        include_receipt=False,
        pair_result_cache={},
        search_context=CoupledSearchContext(),
    )
    assert fast["participants"] == legacy["participants"]
    assert fast["participants"][1]["survival"]["healing_reduced"] > 0.0
    assert fast["participants"][1]["survival"]["venom_factor"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 3) Serpent's Fang venom
# ---------------------------------------------------------------------------


def test_serpents_fang_venom_typed_accessor():
    """The venom values come from the item-effects registry, not literals."""
    item = get_item_by_name("Serpent's Fang")
    assert serpents_fang_venom([item], is_melee=True) == (0.5, 3.0)
    assert serpents_fang_venom([item], is_melee=False) == (0.65, 3.0)
    assert serpents_fang_venom([], is_melee=True) is None


def test_serpents_fang_venom_cuts_shield_at_grant_time_melee():
    """A shield granted inside the venom window keeps only 50% (melee)."""
    item = get_item_by_name("Serpent's Fang")
    source = _dummy_combatant("source", "main", items=[item], is_melee=True)
    target = _dummy_combatant("target", "enemy", health=200.0)
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 30.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "venom-hit",
                }
            ]
        },
        {},
        {
            "target": [
                {
                    "time": 1.0,
                    "amount": 100.0,
                    "kind": "shield",
                    "attacker": "ally:Lulu",
                    "source": "authored support shield",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["support_shield_received"] == pytest.approx(50.0)
    assert result["target"]["venom_until"] == pytest.approx(3.0)
    assert result["target"]["venom_factor"] == pytest.approx(0.5)
    assert result["target"]["venom_events"][0]["factor"] == pytest.approx(0.5)


def test_serpents_fang_venom_cuts_shield_at_grant_time_ranged():
    """A ranged Serpent's Fang holder cuts shields by the sourced 35%."""
    item = get_item_by_name("Serpent's Fang")
    source = _dummy_combatant("source", "main", items=[item], is_melee=False)
    target = _dummy_combatant("target", "enemy", health=200.0)
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 30.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "venom-hit",
                }
            ]
        },
        {},
        {
            "target": [
                {
                    "time": 1.0,
                    "amount": 100.0,
                    "kind": "shield",
                    "attacker": "ally:Lulu",
                    "source": "authored support shield",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["support_shield_received"] == pytest.approx(65.0)
    assert result["target"]["venom_factor"] == pytest.approx(0.65)


def test_serpents_fang_venom_expires_after_three_seconds():
    """A shield granted after the venom window expires is not cut."""
    item = get_item_by_name("Serpent's Fang")
    source = _dummy_combatant("source", "main", items=[item], is_melee=True)
    target = _dummy_combatant("target", "enemy", health=200.0)
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 30.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "venom-hit",
                }
            ]
        },
        {},
        {
            "target": [
                {
                    "time": 4.0,
                    "amount": 100.0,
                    "kind": "shield",
                    "attacker": "ally:Lulu",
                    "source": "post-venom shield",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["support_shield_received"] == pytest.approx(100.0)
    assert result["target"]["venom_until"] == pytest.approx(3.0)
    assert result["target"]["venom_factor"] == pytest.approx(1.0)


def test_serpents_fang_venom_requires_the_item():
    """Without Serpent's Fang, shields the target gains are not cut."""
    source = _dummy_combatant("source", "main")
    target = _dummy_combatant("target", "enemy", health=200.0)
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 30.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "plain-hit",
                }
            ]
        },
        {},
        {
            "target": [
                {
                    "time": 1.0,
                    "amount": 100.0,
                    "kind": "shield",
                    "attacker": "ally:Lulu",
                    "source": "authored support shield",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["support_shield_received"] == pytest.approx(100.0)
    assert result["target"]["venom_until"] == 0.0


def test_serpents_fang_venom_end_to_end_cuts_fimbulwinter_shield():
    """Katarina (melee, Serpent's Fang) cuts Ahri's mid-fight shield by 50%."""
    main = get_champion("Katarina")
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 6,
            "ability_ranks": {"Q": 1, "W": 1, "E": 1, "R": 1},
            "auto_attack_uptime": 0.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Ahri", level=18, items=["Fimbulwinter"]).resolve()
    enemy_stats = dict(enemy.stats)
    enemy_stats.update(health=3000.0, armor=0.0, magic_resistance=0.0)
    enemy = replace(enemy, stats=enemy_stats)

    items = [get_item_by_name("Serpent's Fang")]
    result = _build(main, 18, items, params, [enemy])
    enemy_survival = result["participants"][1]["survival"]
    shields = [
        event
        for event in result["support_events"]
        if event.get("kind") == "shield" and event.get("recipient") == "enemy:Ahri"
    ]
    assert shields
    # The venom is active when the shield is granted and the melee cut is
    # the sourced 50% — the shield receipt carries the applied factor.
    assert enemy_survival["venom_factor"] == pytest.approx(0.5)
    for event in shields:
        assert event["venom"]["factor"] == pytest.approx(0.5)
        assert event["applied_amount"] == pytest.approx(event["amount"] * 0.5, abs=0.1)


# ---------------------------------------------------------------------------
# 4) The four anti-heal items, through the public payload boundary
# ---------------------------------------------------------------------------

#: Every ordinary-purchase item whose cached text inflicts outgoing Grievous
#: Wounds, mapped to the damage type that text gates on.
GRIEVOUS_ITEMS = {
    "Morellonomicon": "magic",
    "Oblivion Orb": "magic",
    "Chempunk Chainsword": "physical",
    "Executioner's Calling": "physical",
}
#: One attacker per trigger type, each dealing that type and nothing else:
#: Ziggs with the auto stream off is pure magic, Vayne is physical and true.
#: Their pairing is what exercises the gate in both directions.
TRIGGER_ATTACKERS = {"magic": ("Ziggs", False), "physical": ("Vayne", True)}
#: Dr. Mundo's Maximum Dosage regenerates on a fixed half-second cadence, so
#: the enemy is healing for the whole window whichever attacker faces him.
HEALING_ENEMY = "Dr. Mundo"
HEALING_ENEMY_ID = f"enemy:{HEALING_ENEMY}"
WINDOW = 10.0


def _grievous_payload(champion, items, *, include_auto_attacks):
    """One timed coupled request against the healing enemy."""
    return calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": list(items),
            "fight_mode": "timed",
            "fight_duration": WINDOW,
            "include_auto_attacks": include_auto_attacks,
            "enemies": [{"champion": HEALING_ENEMY, "level": 18, "items": []}],
        }
    )


def _healing_enemy_survival(response):
    return next(
        participant
        for participant in response["combat"]["participants"]
        if participant["participant_id"] == HEALING_ENEMY_ID
    )["survival"]


def _enemy_heals(response):
    return [
        event
        for event in response["combat"]["healing_events"]
        if event["attacker"] == HEALING_ENEMY_ID
    ]


def _sourced_labels(item_name, damage_type):
    """The wound labels the engine composes from this item's cached text."""
    pack = resolve_grievous(
        healing_reduction_profiles([get_item_by_name(item_name)]), damage_type
    )
    assert pack is not None, f"{item_name} declares no {damage_type} wound"
    return list(pack[2])


@pytest.mark.parametrize("item_name,damage_type", sorted(GRIEVOUS_ITEMS.items()))
def test_grievous_item_reduces_enemy_healing_through_the_payload(
    item_name, damage_type
):
    """Each anti-heal item cuts the enemy's healing by the patch factor."""
    champion, autos = TRIGGER_ATTACKERS[damage_type]
    baseline = _healing_enemy_survival(
        _grievous_payload(champion, [], include_auto_attacks=autos)
    )
    response = _grievous_payload(champion, [item_name], include_auto_attacks=autos)
    wounded = _healing_enemy_survival(response)

    assert baseline["healing_received"] > 0.0
    assert baseline["healing_reduced"] == 0.0
    assert baseline["healing_reduction_events"] == []

    assert wounded["healing_reduced"] > 0.0
    labels = _sourced_labels(item_name, damage_type)
    for event in wounded["healing_reduction_events"]:
        assert event["recipient"] == HEALING_ENEMY_ID
        assert event["sources"] == labels
        assert event["factor"] == pytest.approx(GRIEVOUS_WOUNDS_FACTOR)
        assert event["until"] - event["time"] == pytest.approx(
            GRIEVOUS_WOUNDS_DURATION, abs=1e-3
        )

    cut = [
        event
        for event in _enemy_heals(response)
        if event["healing_reduction_factor"] == pytest.approx(GRIEVOUS_WOUNDS_FACTOR)
    ]
    assert cut, "no heal landed inside the wound window"
    for event in cut:
        assert event["reduced_amount"] == pytest.approx(
            event["raw_amount"] * GRIEVOUS_WOUNDS_FACTOR, abs=0.1
        )


@pytest.mark.parametrize("item_name,damage_type", sorted(GRIEVOUS_ITEMS.items()))
def test_grievous_item_without_its_trigger_damage_type_reduces_nothing(
    item_name, damage_type
):
    """Morello on an attacker who deals no magic wounds nobody, and the
    physical pair is equally inert on a magic-only kit."""
    other = "physical" if damage_type == "magic" else "magic"
    champion, autos = TRIGGER_ATTACKERS[other]
    response = _grievous_payload(champion, [item_name], include_auto_attacks=autos)

    assert response["damage_by_type"][damage_type] == 0.0
    survival = _healing_enemy_survival(response)
    assert survival["healing_received"] > 0.0
    assert survival["healing_reduced"] == 0.0
    assert survival["healing_reduction_events"] == []
    assert all(
        event["healing_reduction_factor"] == pytest.approx(1.0)
        for event in _enemy_heals(response)
    )


def test_grievous_window_expires_between_triggers_in_a_timed_walk():
    """A heal that lands after the 3s window and before the next qualifying
    hit is not reduced at all — the wound is timed, not a fight-long flag."""
    champion, autos = TRIGGER_ATTACKERS["magic"]
    response = _grievous_payload(
        champion, ["Morellonomicon"], include_auto_attacks=autos
    )
    survival = _healing_enemy_survival(response)
    windows = [
        (event["time"], event["until"])
        for event in survival["healing_reduction_events"]
    ]
    assert windows

    lapsed = []
    for event in _enemy_heals(response):
        live = any(start <= event["time"] < until for start, until in windows)
        assert event["healing_reduction_factor"] == pytest.approx(
            GRIEVOUS_WOUNDS_FACTOR if live else 1.0
        )
        if not live and event["time"] > windows[0][1]:
            lapsed.append(event)

    assert lapsed, "the walk never let a wound window lapse"
    for event in lapsed:
        assert event["reduced_amount"] == pytest.approx(event["raw_amount"])


def test_a_wounded_lifeline_heal_is_cut_like_any_authored_heal():
    """Protoplasm Harness fires its heal as the Lifeline arms.

    That heal never reaches the walk's heal author — ``shield_ledger``
    delivers it inside the arming instant — so it needs its own receipt
    that the wound reached it.  Two arms, identical but for the wound.
    """
    protoplasm = get_item_by_name("Protoplasm Harness")
    shen = get_champion("Shen")
    sourced_heal = resolve_starting_defenses(
        "Shen", 18, calculate_total_stats(shen, 18, [protoplasm]), [protoplasm]
    ).threshold_health_heal
    assert sourced_heal > 0.0

    def lifeline_arm(items):
        payload = calculate_payload(
            {
                "champion": "Ziggs",
                "level": 18,
                "items": list(items),
                "fight_mode": "timed",
                "fight_duration": 15.0,
                "include_auto_attacks": False,
                "enemies": [
                    {
                        "champion": "Shen",
                        "level": 18,
                        "items": ["Protoplasm Harness"],
                    }
                ],
            }
        )
        survival = next(
            participant
            for participant in payload["combat"]["participants"]
            if participant["participant_id"] == "enemy:Shen"
        )
        assert survival["survival"]["threshold_health_triggered"] is True
        return survival["survival"]

    burst = ["Rabadon's Deathcap", "Void Staff", "Shadowflame"]
    unwounded = lifeline_arm(burst)
    wounded = lifeline_arm(burst + ["Morellonomicon"])

    assert unwounded["healing_received"] == pytest.approx(sourced_heal)
    assert unwounded["healing_reduced"] == 0.0
    assert wounded["healing_reduction_until"] > 0.0
    assert wounded["healing_received"] == pytest.approx(
        sourced_heal * GRIEVOUS_WOUNDS_FACTOR
    )
    assert wounded["healing_reduced"] == pytest.approx(
        sourced_heal * (1.0 - GRIEVOUS_WOUNDS_FACTOR)
    )


@pytest.mark.parametrize("item_name,damage_type", sorted(GRIEVOUS_ITEMS.items()))
def test_compiled_search_walk_prices_the_wound_like_the_receipt_walk(
    item_name, damage_type
):
    """The optimizer's compiled walk resolves the pre-built Grievous pack to
    the same numbers the per-event receipt walk derives."""
    champion, _ = TRIGGER_ATTACKERS[damage_type]
    main = get_champion(champion)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": WINDOW,
            "include_auto_attacks": True,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion=HEALING_ENEMY, level=18, items=[]).resolve()
    items = [get_item_by_name(item_name)]

    def timeline(**kwargs):
        stats = calculate_total_stats(main, 18, items)
        return build_participant_timeline(
            main,
            18,
            items,
            params,
            main_stats=stats,
            main_defenses=resolve_starting_defenses(champion, 18, stats, items),
            enemies=[enemy],
            allies=[],
            **kwargs,
        )

    receipt = timeline()
    compiled = timeline(
        pair_result_cache={},
        search_context=CoupledSearchContext(),
        include_receipt=False,
    )
    receipt_survival = {
        participant["participant_id"]: participant["survival"]
        for participant in receipt["participants"]
    }
    compiled_survival = {
        participant["participant_id"]: participant["survival"]
        for participant in compiled["participants"]
    }
    assert receipt_survival[HEALING_ENEMY_ID]["healing_reduced"] > 0.0
    assert compiled_survival == receipt_survival
