"""Focused Renata W Bailout source and runtime contract matrix.

Live tests pin the cached source, typed atoms, API validation, and Renata E
ally-support regressions.

Bailout's ACTIVE half (the ramping attack-speed/movement-speed buff, its 5s
window, the 6s takedown refresh, and the 20% post-takedown health) is fully
sourced and modelled.  Its LETHAL-DAMAGE half is not: the cached
lethal-damage description states a 10%-maximum-health burn every 0.264
seconds and calls it true damage, the same entry's notes call the loss raw
damage, and the local 16.15 game binary carries ``TicksPerSecond = 4``.  No
local source resolves either conflict, so the restore, the burn, and the
sourced precedence over resurrection/zombie-state effects are withheld
behind named public denial receipts (``renata_glasc.BAILOUT_AUTHORITY``)
rather than published as a survival number nothing can source.  The rows
below assert that refusal directly instead of deferring it to an xfail.
"""

import hashlib
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator import ability_atoms
from src.calculator.ability_atoms import (
    AbilityAtomQuery,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from src.calculator.champions import renata_glasc
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.participant_timeline import build_participant_timeline
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import derive_ally_effects

CHAMPION = "Renata Glasc"
ATOM_CHAMPION = "Renata"
BAILOUT = "Bailout"
W_SOURCE = {
    "label": "Renata Glasc W ability entry",
    "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Renata_Glasc/W",
    "revision_id": 3394722,
    "revision_timestamp": "2022-02-02T01:32:47Z",
}
ROOT = Path(__file__).resolve().parents[1]


def _w_ability():
    return get_champion(CHAMPION)["abilities"]["W"][0]


def _w_effects(*, ap=100.0):
    return derive_ally_effects(
        get_champion(CHAMPION),
        18,
        {"ability_power": ap, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": "W", "time": 0.0}],
        ability_ranks={"W": 5},
    )


def _bailout_effect():
    """The applied Bailout buff packet (never one of its denial receipts)."""
    return next(
        effect
        for effect in _w_effects()
        if BAILOUT in effect["source"] and effect["kind"] == "stat_buff"
    )


def _bailout_denials(combat, component=None):
    """Public Bailout denial receipts, optionally one named component."""
    return [
        row
        for row in combat.get("item_denial_receipts", [])
        if BAILOUT in str(row.get("source", ""))
        and (component is None or row.get("denied_component") == component)
    ]


def _calculate(payload):
    return app_module.app.test_client().post("/api/calculate", json=payload)


def _lethal_payload(*, duration=4.0, items=None):
    return {
        "champion": CHAMPION,
        "level": 1,
        "items": items or [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 0, "W": 1, "E": 0, "R": 0},
        "enemies": [
            {
                "champion": "Caitlyn",
                "level": 18,
                "items": [
                    "Infinity Edge",
                    "The Collector",
                    "Bloodthirster",
                    "Phantom Dancer",
                    "Kraken Slayer",
                ],
                "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
            }
        ],
    }


def _combat(payload):
    response = _calculate(payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _main_survival(combat):
    return next(
        row["survival"]
        for row in combat["participants"]
        if row["participant_id"] == "main"
    )


def _bailout_public_events(combat):
    return [
        event
        for event in combat.get("support_events", [])
        if BAILOUT in str(event.get("source", ""))
    ]


def test_cached_w_source_pins_all_behavior_numbers_and_precedence():
    ability = _w_ability()
    active = ability["effects"][0]["description"]
    lethal = ability["effects"][1]["description"]
    assert ability["name"] == BAILOUT
    assert ability["targeting"] == "Unit"
    assert "for 5 seconds" in active
    assert "duration resets whenever the target scores a takedown" in active
    assert "restored to 100% of their maximum health" in lethal
    assert "10% of their maximum health every 0.264 seconds" in lethal
    assert "setting their current health to 20%" in lethal
    assert "only once per application" in lethal
    assert (
        "takes priority over all  resurrection and  zombie state effects"
        in ability["notes"]
    )


def test_module_and_api_expose_the_exact_w_source_receipt():
    assert W_SOURCE in renata_glasc.SOURCES
    metadata = app_module.app.test_client().get("/api/config").get_json()
    assert W_SOURCE in metadata["champion_options"][CHAMPION]["sources"]


@pytest.mark.parametrize(
    ("attribute", "modifier", "rank_value", "values", "atom_hash"),
    [
        ("Bonus Attack Speed", 0, 30.0, [10, 15, 20, 25, 30], "733a5a24f38dc26c"),
        ("Bonus Attack Speed", 1, 1.0, [1, 1, 1, 1, 1], "cfeff805cd148975"),
        (
            "Maximum Bonus Attack Speed",
            0,
            60.0,
            [20, 30, 40, 50, 60],
            "7f9f7776c16e680a",
        ),
        ("Maximum Bonus Attack Speed", 1, 2.0, [2, 2, 2, 2, 2], "2bdd5c756458eec6"),
        ("Bonus Movement Speed", 0, 20.0, [10, 12.5, 15, 17.5, 20], "99ba929b7fe59e56"),
        ("Bonus Movement Speed", 1, 1.0, [1, 1, 1, 1, 1], "a38082eea2c2d5bd"),
        (
            "Maximum Bonus Movement Speed",
            0,
            40.0,
            [20, 25, 30, 35, 40],
            "a401bc4135d356d9",
        ),
        ("Maximum Bonus Movement Speed", 1, 2.0, [2, 2, 2, 2, 2], "941ed3f7d59fe1b9"),
    ],
)
def test_ranked_w_atoms_have_exact_values_and_receipts(
    attribute, modifier, rank_value, values, atom_hash
):
    value, atom = required_ranked_attribute_atom(
        ATOM_CHAMPION,
        get_champion(CHAMPION),
        "W",
        attribute,
        5,
        modifier_index=modifier,
    )
    assert value == pytest.approx(rank_value)
    assert atom["values"] == values
    assert atom["evidence"] == [f"{attribute}@effects[0]"]
    assert atom["hash"] == atom_hash


def test_w_duration_atom_has_exact_source_and_hash():
    atom = required_ability_atom(
        ATOM_CHAMPION,
        get_champion(CHAMPION),
        "W",
        query=AbilityAtomQuery(
            source="Renata.W[0].effects[0].description",
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    assert atom["values"] == [5.0]
    assert atom["units"] == ["s"]
    assert atom["evidence"] == ["active duration@effects[0].description"]
    assert atom["hash"] == "17012927ccec19a4"


def test_module_fails_closed_on_the_local_burn_authority_conflict():
    authority = renata_glasc.BAILOUT_AUTHORITY
    assert authority["runtime_available"] is False
    assert authority["reason"] == "burn_authority_conflict"
    assert authority["wiki_burn_interval_seconds"] == pytest.approx(0.264)
    assert authority["gamefile_ticks_per_second"] == pytest.approx(4.0)
    assert authority["wiki_description_damage_class"] == "true"
    assert authority["wiki_notes_damage_class"] == "raw"
    assert authority["gamefile_path"] == "data/bin/characters/renata.bin.json"
    # The digest is only meaningful as a re-verifiable pointer at the bytes it
    # names, so this row pins its SHAPE and
    # ``test_game_binary_pins_the_conflicting_four_ticks_per_second`` compares
    # it against the actual file.  Asserting a literal prefix here would only
    # compare the constant with itself and would still pass if the receipt
    # pointed at a digest no local file has.
    digest = authority["gamefile_sha256"]
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
    # The denial is about Bailout's LETHAL half (restore-to-full then the
    # maximum-health burn), not about the whole slot: the self cast's
    # ramping bonus attack speed is priced off the cached "Bonus Attack
    # Speed" / "Maximum Bonus Attack Speed" ends, so W's coverage is
    # ``modeled`` while the burn stays fail-closed above.
    assert renata_glasc.MODULE_COVERAGE["W"] == "modeled"


def test_game_binary_pins_the_conflicting_four_ticks_per_second():
    """The named binary really carries the numbers the denial cites.

    ``data/bin/`` is gitignored, so this row skips where the evidence is
    absent instead of asserting an unchecked literal.  Where the evidence IS
    present the digest in ``BAILOUT_AUTHORITY`` must match the file's raw
    bytes: a receipt that names a digest no local file has is not a receipt.
    """
    path = ROOT / renata_glasc.BAILOUT_AUTHORITY["gamefile_path"]
    if not path.exists():
        pytest.skip("local Renata game-file evidence is unavailable")
    raw = path.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == renata_glasc.BAILOUT_AUTHORITY["gamefile_sha256"]
    )
    payload = json.loads(raw.decode("utf-8"))
    spell = payload["Characters/Renata/Spells/RenataWAbility/RenataW"]["mSpell"]
    values = {entry["name"]: entry["values"] for entry in spell["DataValues"]}
    assert values["TicksPerSecond"] == [4.0] * 7
    assert values["TicksBeforeDeath"] == [10.0] * 7
    assert values["TriumphPercent"] == [20.0] * 7
    assert values["TagDuration"] == [6.0] * 7
    # The binary's burn runs TicksBeforeDeath / TicksPerSecond = 2.5s, while
    # the cached description states ten ticks 0.264s apart (2.64s).  Both
    # sides of the withheld cadence are asserted here so the denial can never
    # outlive the disagreement that justifies it.
    binary_burn_seconds = values["TicksBeforeDeath"][0] / values["TicksPerSecond"][0]
    wiki_burn_seconds = (
        values["TicksBeforeDeath"][0]
        * renata_glasc.BAILOUT_AUTHORITY["wiki_burn_interval_seconds"]
    )
    assert binary_burn_seconds == pytest.approx(2.5)
    assert wiki_burn_seconds == pytest.approx(2.64)
    assert binary_burn_seconds != pytest.approx(wiki_burn_seconds)


def test_game_binary_corroborates_every_published_active_half_number():
    """The half that IS published is double-sourced, not wiki-only.

    The active half is the only part of Bailout the runtime publishes, so
    the binary must agree with the cached leveling rows the packet reads.
    Ranks 1-5 are binary indices 1-5 (index 0 is the rank-0 slot), the
    per-100-AP ratio is ``APToPercentRatio`` (0.01 -> 1%), and the maximum
    is ``MaxStatMultiplier`` (2x -> the 2% per 100 AP ceiling row).
    """
    path = ROOT / renata_glasc.BAILOUT_AUTHORITY["gamefile_path"]
    if not path.exists():
        pytest.skip("local Renata game-file evidence is unavailable")
    payload = json.loads(path.read_text(encoding="utf-8"))
    spell = payload["Characters/Renata/Spells/RenataWAbility/RenataW"]["mSpell"]
    values = {entry["name"]: entry["values"] for entry in spell["DataValues"]}
    assert values["BonusAttackSpeed"][1:6] == [10.0, 15.0, 20.0, 25.0, 30.0]
    assert values["BonusMoveSpeed"][1:6] == [10.0, 12.5, 15.0, 17.5, 20.0]
    assert values["APToPercentRatio"][5] == pytest.approx(0.01, abs=1e-6)
    assert values["MaxStatMultiplier"] == [2.0] * 7
    assert values["Duration"] == [5.0] * 7

    # The exact rank-5 / 100-AP numbers the packet publishes, rebuilt from the
    # binary alone: 30 + 1 = 31 attack speed, doubled to 62 at maximum ramp.
    effect = _bailout_effect()  # rank 5 at the fixture's 100 ability power
    ap_percent = values["APToPercentRatio"][5] * 100.0
    initial_as = values["BonusAttackSpeed"][5] + ap_percent
    initial_ms = values["BonusMoveSpeed"][5] + ap_percent
    maximum = values["MaxStatMultiplier"][5]
    assert effect["bonus_attack_speed_percent"] == pytest.approx(initial_as)
    assert effect["maximum_bonus_attack_speed_percent"] == pytest.approx(
        initial_as * maximum
    )
    assert effect["bonus_move_speed_percent"] == pytest.approx(initial_ms)
    assert effect["maximum_bonus_move_speed_percent"] == pytest.approx(
        initial_ms * maximum
    )
    assert effect["duration"] == pytest.approx(values["Duration"][5])
    assert effect["takedown_window"] == pytest.approx(values["TagDuration"][5])
    assert effect["takedown_health_ratio"] == pytest.approx(
        values["TriumphPercent"][5] / 100.0
    )


@pytest.mark.parametrize("case", ["missing", "empty", "malformed"])
def test_w_atom_access_fails_closed_for_missing_or_malformed_values(monkeypatch, case):
    query = AbilityAtomQuery(
        source="Renata.W[0].effects[0].leveling[0].modifiers[0]",
        behavior="ability",
        evidence_prefix="Bonus Attack Speed@",
    )
    if case == "missing":
        rows = {"W": ()}
        expected = KeyError
    else:
        atom = {
            "source": query.source,
            "behavior": query.behavior,
            "evidence": ["Bonus Attack Speed@effects[0]"],
            "values": [] if case == "empty" else ["30"],
            "units": [] if case == "empty" else ["%"],
        }
        rows = {"W": (atom,)}
        expected = ValueError if case == "empty" else TypeError
    monkeypatch.setattr(ability_atoms, "_ability_atoms", lambda *_args: rows)
    with pytest.raises(expected, match="ability atom"):
        required_ability_atom(ATOM_CHAMPION, {}, "W", query=query)


def test_existing_renata_e_ally_support_packet_remains_intact():
    effects = derive_ally_effects(
        get_champion(CHAMPION),
        18,
        {"ability_power": 100.0, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": "E", "time": 1.0}],
        ability_ranks={"E": 5},
    )
    shield = next(event for event in effects if event["kind"] == "shield")
    assert shield["source"] == "Loyalty Program · Shield Strength"
    assert shield["amount"] == pytest.approx(160.0)
    assert shield["duration"] == pytest.approx(3.0)
    assert shield["target_scope"] == "all_teammates"


@pytest.mark.parametrize(
    "selections",
    [[], {"buff:W:0": "0"}, {"buff:W:0": 5}],
)
def test_api_rejects_malformed_support_target_selections(selections):
    payload = _lethal_payload()
    payload["support_target_selections"] = selections
    response = _calculate(payload)
    assert response.status_code == 400
    assert "support_target_selections" in response.get_json()["error"]


def test_w_packet_admits_self_or_one_selected_ally():
    effect = _bailout_effect()
    assert effect["target_self"] is True
    assert effect["target_scope"] == "one_teammate"
    assert effect["target_selection_key"]


def test_w_rank_five_at_100_ap_exposes_initial_and_maximum_buff_values():
    effect = _bailout_effect()
    assert effect["bonus_attack_speed_percent"] == pytest.approx(31.0)
    assert effect["maximum_bonus_attack_speed_percent"] == pytest.approx(62.0)
    assert effect["bonus_move_speed_percent"] == pytest.approx(21.0)
    assert effect["maximum_bonus_move_speed_percent"] == pytest.approx(42.0)


def test_w_packet_receipts_duration_and_takedown_refresh_rule():
    effect = _bailout_effect()
    assert effect["duration"] == pytest.approx(5.0)
    assert effect["refresh_duration"] == pytest.approx(5.0)
    assert effect["refresh_trigger"] == "takedown_within_6_seconds"


def test_lethal_damage_under_bailout_publishes_a_named_restore_denial():
    """The restore is sourced but unpublishable, so it is NAMED, not faked.

    The cached lethal-damage description states a restore to 100% maximum
    health; the burn that immediately follows it has no single local
    authority (``BAILOUT_AUTHORITY``), so publishing the restore alone would
    overstate survival.  The packet therefore carries the sourced SHAPE
    (ratio 1.0, unavailable, named reason) while the public receipt carries
    the denial, and no revive is attributed to Bailout anywhere.
    """
    effect = _bailout_effect()
    assert effect["lethal_restore_available"] is False
    assert effect["lethal_restore_denial"] == "burn_authority_conflict"
    # "restored to 100% of their maximum health" — read from the cache.
    assert effect["lethal_restore_ratio"] == pytest.approx(1.0)

    combat = _combat(_lethal_payload())
    assert _bailout_public_events(combat)
    survival = _main_survival(combat)
    assert survival["revived"] is False
    assert survival["revive_source"] == ""
    assert survival["revive_health_restored"] == pytest.approx(0.0)

    denials = _bailout_denials(combat, "lethal_damage_restore")
    assert len(denials) == 1
    assert denials[0]["reason"] == "burn_authority_conflict"
    assert denials[0]["target"] == "main"
    assert denials[0]["source_url"] == W_SOURCE["url"]
    assert denials[0]["source_revision_id"] == W_SOURCE["revision_id"]


def test_no_burn_damage_is_published_while_the_cadence_conflict_stands():
    """No Bailout burn tick may be published from two disagreeing sources.

    The cached description states one 10%-maximum-health tick every 0.264s
    and calls the loss true damage; the same entry's notes call it raw
    damage, and the local game binary carries four ticks per second.  A
    survival kernel cannot hold both cadences or both damage classes, so
    the burn is withheld behind a named receipt and this test proves BOTH
    sides of the conflict are still live in the cache.
    """
    ability = _w_ability()
    lethal = ability["effects"][1]["description"]
    assert "10% of their maximum health every 0.264 seconds" in lethal
    assert "true damage burn" in lethal
    assert "self-damage taken is considered  raw damage" in ability["notes"]
    authority = renata_glasc.BAILOUT_AUTHORITY
    assert authority["wiki_burn_interval_seconds"] != pytest.approx(
        1.0 / authority["gamefile_ticks_per_second"]
    )
    assert (
        authority["wiki_description_damage_class"]
        != authority["wiki_notes_damage_class"]
    )

    combat = _combat(_lethal_payload())
    ticks = [
        event
        for event in combat["events"]
        if BAILOUT in str(event.get("source", ""))
        and float(event.get("damage", 0.0)) > 0.0
    ]
    assert ticks == []
    denials = _bailout_denials(combat, "maximum_health_burn")
    assert len(denials) == 1
    assert denials[0]["reason"] == "burn_authority_conflict"


def test_successful_takedown_stops_burn_and_sets_twenty_percent_health():
    effect = _bailout_effect()
    assert effect["takedown_stops_burn"] is True
    assert effect["takedown_health_ratio"] == pytest.approx(0.20)


def test_one_application_receipts_exactly_one_denial_set_per_cast():
    """One Bailout application == one withheld lethal activation.

    "This effect may occur only once per application of Bailout" — the
    cached rule the packet receipts.  Because the activation itself is
    withheld, the observable one-per-application invariant is that each
    accepted cast publishes exactly one denial row per withheld component,
    never a second stacked copy.
    """
    effect = _bailout_effect()
    assert effect["lethal_activations_per_application"] == 1

    combat = _combat(_lethal_payload())
    denials = _bailout_denials(combat)
    components = [row["denied_component"] for row in denials]
    assert sorted(components) == sorted(
        renata_glasc.BAILOUT_AUTHORITY["denied_survival_components"]
    )
    assert len(components) == len(set(components))
    assert effect["denied_survival_components"] == list(
        renata_glasc.BAILOUT_AUTHORITY["denied_survival_components"]
    )


def test_resurrection_precedence_over_guardian_angel_is_named_not_assumed():
    """A Guardian Angel revive beside Bailout carries a coexisting denial.

    The cached notes say Bailout "takes priority over all resurrection and
    zombie state effects", so on a Bailout-covered participant the GA row
    is not, by itself, the complete sourced outcome — Bailout's own restore
    would have pre-empted it, and that restore is unpublishable (no priced
    model for the pre-empted branch exists). The model does not suppress
    Guardian Angel's row to fake that precedence: GA still revives and its
    survival row still publishes (`revive_source == "Guardian Angel
    (Rebirth)"`, since Bailout is absent from `_CHAMPION_REVIVE_SOURCES`).
    What the model adds is a *named* `resurrection_precedence` denial on the
    same participant, disclosing the gap instead of leaving it silent — and
    it never credits Bailout with a revive it cannot price.
    """
    effect = _bailout_effect()
    assert (
        effect["resurrection_precedence"]
        == "over_all_resurrection_and_zombie_state_effects"
    )
    assert (
        "takes priority over all  resurrection and  zombie state effects"
        in _w_ability()["notes"]
    )

    # 6s window: Guardian Angel's Rebirth resolves at 4.0s, so this is the
    # exact fight where an unreceipted model would publish its revive.
    combat = _combat(_lethal_payload(duration=6.0, items=["Guardian Angel"]))
    survival = _main_survival(combat)
    assert BAILOUT not in survival["revive_source"]
    denials = _bailout_denials(combat, "resurrection_precedence")
    assert len(denials) == 1
    assert denials[0]["target"] == "main"
    assert denials[0]["reason"] == "burn_authority_conflict"


def test_zombie_state_precedence_is_named_for_a_supported_ally_target():
    """The ally-cast admission works; the zombie-state half stays closed.

    A rostered Renata casting W on the main participant resolves the
    sourced self-or-one-ally scope to that participant, so the buff and its
    denials are attributed to the right pair.  No zombie state exists in
    this model, and Bailout's sourced precedence over one cannot be
    exercised, so the precedence row is published as a named denial rather
    than as an unsourced revive.
    """
    payload = _lethal_payload()
    payload["champion"] = "Sion"
    payload["ability_ranks"] = {"Q": 0, "W": 0, "E": 0, "R": 0}
    payload["allies"] = [
        {
            "champion": CHAMPION,
            "level": 1,
            "items": [],
            "ally_effects_enabled": True,
            "ability_ranks": {"Q": 0, "W": 1, "E": 0, "R": 0},
        }
    ]
    combat = _combat(payload)
    assert any(event["target"] == "main" for event in _bailout_public_events(combat))
    denials = _bailout_denials(combat, "resurrection_precedence")
    assert len(denials) == 1
    assert denials[0]["target"] == "main"
    assert denials[0]["attacker"] == f"ally:{CHAMPION}"
    assert BAILOUT not in _main_survival(combat)["revive_source"]


def test_roster_loadout_accepts_a_bounded_target_current_health_input():
    loadout = ChampionLoadout.from_request(
        {"champion": "Caitlyn", "level": 1, "current_health": 100.0},
        field="enemies[0]",
    )
    assert loadout.current_health == pytest.approx(100.0)


def test_api_rejects_malformed_roster_target_current_health():
    payload = _lethal_payload()
    payload["enemies"][0]["current_health"] = "low"
    response = _calculate(payload)
    assert response.status_code == 400
    assert "current_health" in response.get_json()["error"]


@pytest.mark.parametrize("value", [0.0, -5.0, float("nan"), float("inf"), True])
def test_api_rejects_out_of_range_roster_target_current_health(value):
    """The bound is (0, max health]; every other input fails closed."""
    payload = _lethal_payload()
    payload["enemies"][0]["current_health"] = value
    response = _calculate(payload)
    assert response.status_code == 400
    assert "current_health" in response.get_json()["error"]


def test_roster_target_current_health_above_maximum_fails_closed():
    """A starting health the build cannot provide raises, never clamps.

    Silently clamping would answer a question nobody asked (the caller
    believes the target has more health than it does), so the resolver names
    the champion and its resolved maximum instead.
    """
    payload = _lethal_payload()
    payload["enemies"][0]["current_health"] = 99999.0
    response = _calculate(payload)
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "current_health must not exceed" in error
    assert "Caitlyn" in error


def _current_health_probe(current_health=None):
    enemy = {
        "champion": "Caitlyn",
        "level": 18,
        "items": [],
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
    }
    if current_health is not None:
        enemy["current_health"] = current_health
    return {
        "champion": CHAMPION,
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 8.0,
        "include_auto_attacks": True,
        "ability_ranks": {"Q": 5, "W": 1, "E": 5, "R": 3},
        "enemies": [enemy],
    }


def test_roster_target_current_health_starts_the_fight_below_full_health():
    """The input is live state, not a decorative field.

    Bailout's lethal half needs a target that can actually take fatal damage,
    so the roster input has to reach the survival walk.  The same enemy that
    survives the fight at full health dies immediately when it starts at 100
    health, and the ledger charges exactly the 100 health that existed —
    never the full maximum-health pool.
    """
    full = _combat(_current_health_probe())
    wounded = _combat(_current_health_probe(100.0))

    def enemy_row(combat):
        return next(
            row["survival"]
            for row in combat["participants"]
            if row["participant_id"] != "main"
        )

    full_enemy = enemy_row(full)
    wounded_enemy = enemy_row(wounded)
    assert full_enemy["terminal_phase"] == "alive"
    assert full_enemy["death_time"] is None
    assert full_enemy["max_health"] == pytest.approx(wounded_enemy["max_health"])

    assert wounded_enemy["terminal_phase"] == "dead"
    assert wounded_enemy["first_death_time"] == pytest.approx(0.0)
    assert wounded_enemy["ending_health"] == pytest.approx(0.0)
    assert wounded_enemy["health_damage"] == pytest.approx(100.0)
    # Maximum health is unchanged, so every ratio effect still reads the pool
    # the build provides rather than the reduced starting health.
    assert wounded_enemy["max_health"] > 100.0


def test_w_score_path_matches_receipt_path_on_bailout_survival_fields():
    """Both walks agree, and the denial is receipt-only.

    Bailout's buff packet is an unrepresentable ``stat_buff`` template for
    the compiled score kernel, so the score path falls back to the shared
    survival walk.  The survival fields must therefore be identical, and
    the denial rows must ride the receipt section alone — never the applied
    support stream that the walk consumes.
    """
    champion = get_champion(CHAMPION)
    stats = calculate_total_stats(champion, 1, [])
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 4.0,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 1, "E": 0, "R": 0},
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(
        champion="Caitlyn",
        level=18,
        items=("Infinity Edge", "The Collector", "Bloodthirster"),
        ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
    ).resolve()
    kwargs = {
        "main_stats": stats,
        "main_defenses": resolve_starting_defenses(CHAMPION, 1, stats, []),
        "enemies": [enemy],
        "allies": [],
    }
    receipt = build_participant_timeline(
        champion, 1, [], params, include_receipt=True, **kwargs
    )
    score = build_participant_timeline(
        champion, 1, [], params, include_receipt=False, **kwargs
    )
    receipt_survival = _main_survival(receipt)
    score_survival = _main_survival(score)
    assert BAILOUT not in receipt_survival["revive_source"]
    for key in (
        "revived",
        "revive_health_restored",
        "revive_source",
        "first_death_time",
        "death_time",
        "terminal_phase",
    ):
        assert score_survival[key] == receipt_survival[key]
    # The denial rides the receipt section only: the score path publishes no
    # receipt sections at all, and neither path may apply a Bailout packet
    # as a survival gain.
    assert [row["denied_component"] for row in _bailout_denials(receipt)] == list(
        renata_glasc.BAILOUT_AUTHORITY["denied_survival_components"]
    )
    assert "item_denial_receipts" not in score
    assert not any(
        BAILOUT in str(event.get("source", ""))
        for event in receipt.get("healing_events", [])
    )
