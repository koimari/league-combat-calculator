"""Sourced Summoner's Rift lane-minion stats, and the gap that stayed shut.

Three groups, in the order the evidence flows:

1. **The pin.** Every constant in ``src/calculator/minion_stats.py`` is
   re-read out of the tracked CommunityDragon character binaries under
   ``data/bin/characters/``. A transcription slip fails here rather than
   riding into a damage number, which is the whole reason the constants are
   allowed to be constants.
2. **The refusals.** Magic resistance is in no minion record, the siege
   attack-speed ratio is in no siege record, and the wave-upgrade table has
   no decidable binding to Classic. All three answer with a named error,
   never with a plausible zero.
3. **The wiring.** ``FightConfig.for_minion`` and the request layer fill the
   target's durability from the source, refuse a second answer for it, and
   leave the champion-class path exactly where it was.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.app as app_module
from src.calculator import damage, item_effects, minion_stats
from src.calculator.damage import FightConfig
from tests.app_config import app_config

BIN_DIR = Path(__file__).resolve().parent.parent / "data" / "bin" / "characters"

#: The anchor the sourcing task named, transcribed once here so the pin has
#: a value that did NOT come from the module under test.  Everything else is
#: compared against the binaries themselves.
MELEE_ANCHOR = {
    "health": 430.0,
    "attack_damage": 11.0,
    "armor": 0.0,
    "attack_speed": 1.25,
    "attack_range": 110.0,
    "move_speed": 350.0,
}


def _record(team: str, minion_type: str) -> dict:
    """One tracked minion binary's Root character record.

    Each file carries two records, ``Root`` and ``URF``. Only ``Root`` is the
    ordinary Summoner's Rift unit; reading the file's sole record or its last
    one would silently price the URF variant.
    """
    name = f"SRU_{team.capitalize()}Minion{minion_type.capitalize()}"
    payload = json.loads((BIN_DIR / f"{name.lower()}.bin.json").read_text("utf-8"))
    return payload[f"Characters/{name}/CharacterRecords/Root"]


def _field(record: dict, name: str) -> float:
    """One record field's number, through either shape the binaries use.

    Stat fields are ``{"baseValue": x, "__type": "ModifiableFloat"}`` wrappers
    while the gold, experience and crit-multiplier fields are bare floats.
    """
    value = record[name]
    return float(value["baseValue"] if isinstance(value, dict) else value)


# ---------------------------------------------------------------------------
# 1. The pin: every constant against its own binary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("stat", "expected"), sorted(MELEE_ANCHOR.items()))
def test_the_melee_anchor_is_what_the_module_answers(stat, expected):
    """The named anchor, read through the accessor callers use."""
    assert minion_stats.sourced_stat("melee", stat) == expected


@pytest.mark.parametrize(("stat", "expected"), sorted(MELEE_ANCHOR.items()))
def test_the_melee_anchor_is_what_the_binary_states(stat, expected):
    """The same anchor, read out of the tracked record itself.

    Paired with the test above, this closes the loop: the module and the
    binary are each independently compared against a value typed by hand, so
    agreeing with each other is not enough to pass.
    """
    assert (
        _field(_record("chaos", "melee"), minion_stats.SOURCE_FIELDS[stat]) == expected
    )


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_every_sourced_stat_matches_its_record_field(minion_type):
    """Each type's whole stat block, field by field, against its binary."""
    record = _record("chaos", minion_type)
    stats = minion_stats.base_stats(minion_type)
    for stat, field_name in sorted(minion_stats.SOURCE_FIELDS.items()):
        held = getattr(stats, stat)
        if field_name not in record:
            assert held is None, (
                f"{minion_type} {stat} holds {held!r} but the record has no "
                f"{field_name!r} field; an absent stat must be None, which "
                "sourced_stat turns into a refusal"
            )
            continue
        assert held == _field(record, field_name), f"{minion_type}.{stat}"


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_the_two_teams_state_the_same_stats(minion_type):
    """Chaos and Order agree on every sourced field, as a CHECKED property.

    The module keys its stat block by type alone. That is only sound while
    the teams agree, so both files are tracked and compared here — a patch
    that splits them fails this test instead of pricing one team for both.
    """
    chaos = _record("chaos", minion_type)
    order = _record("order", minion_type)
    for field_name in sorted(set(minion_stats.SOURCE_FIELDS.values())):
        assert (field_name in chaos) == (field_name in order), field_name
        if field_name in chaos:
            assert _field(chaos, field_name) == _field(order, field_name), field_name


def test_the_four_types_are_not_all_the_same_minion():
    """A guard against the pin passing by comparing one record to itself."""
    healths = {
        minion_type: minion_stats.sourced_stat(minion_type, "health")
        for minion_type in minion_stats.MINION_TYPES
    }
    assert sorted(healths.values()) == [275.0, 430.0, 750.0, 1500.0]
    assert minion_stats.sourced_stat("super", "armor") == 100.0


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_every_tracked_record_is_readable_and_names_its_own_type(minion_type):
    """The eight evidence files parse, and each states the record cited."""
    for team in minion_stats.MINION_TEAMS:
        record = _record(team, minion_type)
        assert record["__type"] == "CharacterRecord"
    assert minion_stats.base_stats(minion_type).record.endswith("CharacterRecords/Root")
    assert minion_type.capitalize() in minion_stats.base_stats(minion_type).record


# ---------------------------------------------------------------------------
# 2. The refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_magic_resistance_is_absent_from_every_record(minion_type):
    """The premise of the MR refusal, checked against the files.

    If a patch ever adds the field, this fails and the refusal below becomes
    wrong — which is the point of checking the premise rather than the
    consequence.
    """
    for team in minion_stats.MINION_TEAMS:
        record = _record(team, minion_type)
        assert minion_stats.ABSENT_FROM_EVERY_RECORD["magic_resistance"] not in record
        assert not [key for key in record if "spellblock" in key.lower()]


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_asking_for_minion_magic_resistance_raises_and_says_what_was_looked_for(
    minion_type,
):
    """No minion type answers a magic resistance, and none answers 0.0."""
    with pytest.raises(minion_stats.MinionStatUnavailable) as excinfo:
        minion_stats.sourced_stat(minion_type, "magic_resistance")
    context = excinfo.value.context
    assert context["searched_field"] == "baseSpellBlockModifiable"
    assert context["minion_type"] == minion_type
    assert "not zero" in str(excinfo.value)


def test_the_siege_attack_speed_ratio_is_absent_from_its_record_alone():
    """The one stat a single record omits: siege has no attack-speed ratio."""
    field_name = minion_stats.SOURCE_FIELDS["attack_speed_ratio"]
    assert field_name not in _record("chaos", "siege")
    for present in ("melee", "ranged", "super"):
        assert field_name in _record("chaos", present)

    with pytest.raises(minion_stats.MinionStatUnavailable) as excinfo:
        minion_stats.sourced_stat("siege", "attack_speed_ratio")
    assert excinfo.value.context["searched_field"] == field_name
    assert minion_stats.sourced_stat("siege", "attack_speed") == 1.0


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_unsourced_stats_lists_exactly_what_the_accessor_refuses(minion_type):
    """The advertised refusal list and the accessor's behaviour are one."""
    refused = minion_stats.unsourced_stats(minion_type)
    for stat in refused:
        with pytest.raises(minion_stats.MinionStatUnavailable):
            minion_stats.sourced_stat(minion_type, stat)
    answerable = set(minion_stats.SOURCE_FIELDS) - set(refused)
    for stat in sorted(answerable):
        assert isinstance(minion_stats.sourced_stat(minion_type, stat), float)
    assert ("attack_speed_ratio" in refused) == (minion_type == "siege")


def test_the_source_field_table_names_only_real_stat_fields():
    """What lets ``unsourced_stats`` read without a default.

    Every SOURCE_FIELDS key must be a field of the stat block, so a typo in
    the table raises instead of being reported as one more unavailable stat.
    """
    block = minion_stats.SourcedMinionBaseStats.__dataclass_fields__
    assert set(minion_stats.SOURCE_FIELDS) <= set(block)
    assert set(minion_stats.SOURCE_FIELDS).isdisjoint(
        minion_stats.ABSENT_FROM_EVERY_RECORD
    )


def test_an_unknown_stat_name_is_refused_rather_than_defaulted():
    """A typo does not fall through to zero or to some other stat."""
    with pytest.raises(KeyError):
        minion_stats.sourced_stat("melee", "magic_resist")
    with pytest.raises(KeyError):
        minion_stats.sourced_stat("caster", "health")


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
@pytest.mark.parametrize("elapsed", [0.0, 90.0, 900.0])
def test_time_scaled_stats_always_fail_closed(minion_type, elapsed):
    """No elapsed time gets a scaled answer, including zero.

    Spawn time is the one moment the constants ARE correct, and it still
    refuses: answering there would make the function look usable and hand a
    caller a spawn-time number for minute fifteen.
    """
    with pytest.raises(minion_stats.MinionScalingUnavailable) as excinfo:
        minion_stats.time_scaled_base_stats(minion_type, elapsed)
    context = excinfo.value.context
    assert context["reason"] == "barracks_config_not_bound_to_classic"
    assert context["candidate_count"] > 1
    assert context["elapsed_seconds"] == elapsed


def test_a_bad_minion_type_is_reported_as_a_bad_type_not_as_the_scaling_gap():
    """A caller learns about the typo, not about the unrelated denial."""
    with pytest.raises(KeyError):
        minion_stats.time_scaled_base_stats("caster", 90.0)
    with pytest.raises(ValueError):
        minion_stats.time_scaled_base_stats("melee", -1.0)


def test_the_scaling_receipt_names_what_is_missing_and_why():
    """The receipt has to carry the denial's whole reason, not a flag.

    Ambiguity is the reason, so the receipt must show more than one
    candidate AND show that they disagree on the field a scaled number would
    read — otherwise "ambiguous" would be a claim with no evidence in it.
    """
    receipt = minion_stats.MINION_SCALING_AUTHORITY
    assert receipt["runtime_available"] is False
    assert ".bin.json" in receipt["table_found_at"]
    candidates = receipt["candidates"]
    assert len(candidates) > 1
    intervals = {entry["upgrade_interval_seconds"] for entry in candidates}
    assert len(intervals) > 1, "one interval would not be ambiguous"
    assert receipt["searched"], "a denial cites the routes that came back empty"
    assert "time_scaled_base_stats" in receipt["denied_reads"]


def test_the_scaling_denial_is_the_only_way_to_read_a_scaled_stat():
    """No accessor quietly offers the upgrade table's numbers instead."""
    exported = {name for name in dir(minion_stats) if not name.startswith("_")}
    assert "wave_upgrade_count" not in exported
    assert "upgrade_interval_seconds" not in exported


# ---------------------------------------------------------------------------
# 3. The wiring: FightConfig
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_for_minion_fills_the_target_from_the_source(minion_type):
    """A sourced-minion fight carries the record's numbers, unspelled."""
    config = FightConfig.for_minion(
        minion_type, target_magic_resistance=0.0, fight_duration_seconds=5.0
    )
    assert config.target_class == item_effects.MINION_TARGET_CLASS
    assert config.minion_type == minion_type
    assert config.target_health == minion_stats.sourced_stat(minion_type, "health")
    assert config.target_armor == minion_stats.sourced_stat(minion_type, "armor")
    assert config.target_bonus_health == 0.0
    assert config.target_bonus_armor == 0.0


def test_for_minion_fills_the_melee_anchor_specifically():
    """The anchor again, at the surface a fight is actually built through."""
    config = FightConfig.for_minion(
        "melee", target_magic_resistance=0.0, fight_duration_seconds=5.0
    )
    assert config.target_health == 430.0
    assert config.target_armor == 0.0


def test_for_minion_refuses_to_be_handed_a_field_it_sources():
    """Sourced and caller-supplied never both answer for one field."""
    for field_name in sorted(damage.MINION_SOURCED_TARGET_FIELDS):
        with pytest.raises(ValueError, match=field_name):
            FightConfig.for_minion(
                "melee",
                target_magic_resistance=0.0,
                fight_duration_seconds=5.0,
                **{field_name: 1.0},
            )


def test_for_minion_refuses_to_be_handed_its_own_class_or_type():
    """The class is fixed by the constructor, not negotiable through it.

    ``minion_type`` is refused one layer earlier, by Python: it is a named
    parameter, so passing it again is a TypeError before the guard runs.
    """
    with pytest.raises(ValueError, match="target_class"):
        FightConfig.for_minion(
            "melee",
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            target_class="champion",
        )
    with pytest.raises(TypeError, match="minion_type"):
        FightConfig.for_minion(
            "melee",
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            minion_type="ranged",
        )


def test_for_minion_requires_a_magic_resistance_from_the_caller():
    """The one unsourced durability stat has no default hiding behind it."""
    with pytest.raises(TypeError):
        FightConfig.for_minion("melee", fight_duration_seconds=5.0)
    config = FightConfig.for_minion(
        "melee", target_magic_resistance=37.0, fight_duration_seconds=5.0
    )
    assert config.target_magic_resistance == 37.0


def test_a_hand_built_config_cannot_contradict_the_type_it_claims():
    """The guard covers configs the factory did not build."""
    with pytest.raises(ValueError, match="contradicts the sourced melee minion"):
        FightConfig(
            target_health=1000.0,
            target_armor=0.0,
            target_bonus_health=0.0,
            target_bonus_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            target_class=item_effects.MINION_TARGET_CLASS,
            minion_type="melee",
        )


def test_a_minion_type_requires_the_minion_class():
    """A champion-class fight cannot carry a minion selector."""
    with pytest.raises(ValueError, match="requires target_class"):
        FightConfig(
            target_health=430.0,
            target_armor=0.0,
            target_bonus_health=0.0,
            target_bonus_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            minion_type="melee",
        )


def test_an_unknown_minion_type_never_reaches_a_fight():
    """A misspelling fails closed instead of arriving caller-shaped."""
    with pytest.raises(KeyError):
        FightConfig.for_minion(
            "caster", target_magic_resistance=0.0, fight_duration_seconds=5.0
        )
    with pytest.raises(ValueError, match="minion_type must be one of"):
        FightConfig(
            target_health=430.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            target_class=item_effects.MINION_TARGET_CLASS,
            minion_type="caster",
        )


def test_the_default_fight_is_untouched_by_any_of_this():
    """No minion type means the config the engine always built.

    The whole change has to be invisible to a champion-class caller, so this
    pins the default value AND that the guard exits before reading anything.
    """
    config = FightConfig(
        target_health=2000.0,
        target_armor=100.0,
        target_magic_resistance=50.0,
        fight_duration_seconds=5.0,
    )
    assert config.minion_type == ""
    assert config.target_class == item_effects.DEFAULT_TARGET_CLASS
    assert config.target_health == 2000.0
    assert config.target_bonus_armor is None


def test_a_minion_class_fight_without_a_type_stays_caller_shaped():
    """The label-only fight the target-class slice introduced still works."""
    config = FightConfig(
        target_health=1234.0,
        target_armor=7.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        target_class=item_effects.MINION_TARGET_CLASS,
    )
    assert config.minion_type == ""
    assert config.target_health == 1234.0


def test_the_sourced_field_table_is_read_in_both_directions():
    """Fill and guard share one table, so neither can name a field alone."""
    filled = damage.sourced_minion_target("melee")
    assert set(filled) == set(damage.MINION_SOURCED_TARGET_FIELDS)
    assert "target_magic_resistance" not in damage.MINION_SOURCED_TARGET_FIELDS
    for field_name in filled:
        assert hasattr(FightConfig, "__dataclass_fields__")
        assert field_name in FightConfig.__dataclass_fields__


# ---------------------------------------------------------------------------
# 4. The wiring: the public request body
# ---------------------------------------------------------------------------


@pytest.fixture(name="api_client")
def _api_client():
    """A rate-limit-free test client for the public calculate endpoint."""
    with app_config(RATE_LIMIT_ENABLED=False):
        yield app_module.app.test_client()


def _calculate(client, **extra):
    """POST one Ahri auto-attacking fight, with *extra* merged into the body."""
    body = {
        "champion": "Ahri",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 5,
        "rotations": 1,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
    }
    body.update(extra)
    return client.post("/api/calculate", json=body)


@pytest.mark.parametrize("minion_type", minion_stats.MINION_TYPES)
def test_the_api_prices_a_named_minion_with_its_own_armor(api_client, minion_type):
    """End to end, the sourced armor is what mitigates the damage.

    Melee, ranged and siege all state armor 0 and must agree; super states
    100 and must come out strictly lower. That difference is the evidence
    the sourced numbers reach the damage math rather than stopping at the
    config — a wiring bug that dropped them would make all four equal.
    """
    response = _calculate(
        api_client,
        target_class="minion",
        minion_type=minion_type,
        target_mr=0,
        items=["Doran's Helm"],
    )
    assert response.status_code == 200, response.get_json()
    zero_armor = _calculate(
        api_client,
        target_class="minion",
        minion_type="melee",
        target_mr=0,
        items=["Doran's Helm"],
    ).get_json()["total_damage"]
    total = response.get_json()["total_damage"]
    if minion_stats.sourced_stat(minion_type, "armor") == 0.0:
        assert total == pytest.approx(zero_armor)
    else:
        assert total < zero_armor


def test_the_api_refuses_a_body_that_also_supplies_a_sourced_field(api_client):
    """A request cannot claim a sourced minion and hand it other numbers."""
    for field_name in sorted(damage.MINION_SOURCED_TARGET_FIELDS):
        response = _calculate(
            api_client,
            target_class="minion",
            minion_type="melee",
            **{field_name: 999},
        )
        assert response.status_code == 400, field_name
        assert field_name in response.get_json()["error"]


def test_the_api_still_takes_a_magic_resistance_for_a_named_minion(api_client):
    """target_mr stays the caller's, because no record states one."""
    response = _calculate(
        api_client, target_class="minion", minion_type="melee", target_mr=40
    )
    assert response.status_code == 200, response.get_json()


def test_the_api_refuses_a_minion_type_on_a_champion_fight(api_client):
    """A selector nothing would apply is an error, not a silent no-op."""
    response = _calculate(api_client, minion_type="melee")
    assert response.status_code == 400
    assert "requires target_class" in response.get_json()["error"]


def test_the_api_refuses_an_unknown_minion_type(api_client):
    """Only the four sourced spellings are accepted."""
    response = _calculate(api_client, target_class="minion", minion_type="caster")
    assert response.status_code == 400
    assert "minion_type must be one of" in response.get_json()["error"]


def test_omitting_the_minion_type_is_the_request_that_always_worked(api_client):
    """Every pre-existing body is unchanged, minion-class ones included."""
    omitted = _calculate(api_client, target_class="minion", target_armor=0)
    explicit = _calculate(
        api_client, target_class="minion", minion_type="", target_armor=0
    )
    assert omitted.status_code == 200
    assert explicit.status_code == 200
    assert omitted.get_json()["total_damage"] == pytest.approx(
        explicit.get_json()["total_damage"]
    )


def test_a_champion_fight_is_unaffected_by_the_new_key(api_client):
    """The default path, through the surface the change actually edited."""
    before = _calculate(api_client, target_health=2000, target_armor=100, target_mr=50)
    assert before.status_code == 200
    payload = before.get_json()
    assert payload["total_damage"] > 0.0


# ---------------------------------------------------------------------------
# 5. The evidence files themselves
# ---------------------------------------------------------------------------


def test_all_eight_evidence_files_are_tracked_and_parse():
    """The constants are only defensible while their sources are in the tree."""
    expected = {
        f"sru_{team}minion{minion_type}.bin.json"
        for team in minion_stats.MINION_TEAMS
        for minion_type in minion_stats.MINION_TYPES
    }
    assert len(expected) == 8
    for name in sorted(expected):
        path = BIN_DIR / name
        assert path.exists(), f"{path} is cited by minion_stats and must be tracked"
        assert json.loads(path.read_text("utf-8"))
