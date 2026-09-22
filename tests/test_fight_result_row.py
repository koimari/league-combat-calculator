"""Which fight-result keys may be read fail-closed, measured in both modes.

A fight result's membership depends on ``score_only``, so no single-mode
corpus can license a read of one. This walks a spread of champions through
both modes and re-derives the intersection the module claims.
"""

from dataclasses import replace

import pytest

from src.calculator.fight_result_row import (
    FIGHT_RESULT_REQUIRED_FIELDS,
    result_breakdown,
    result_cast_timeline,
    result_damage_events,
    result_keystone,
    result_keystone_state_events,
    result_self_healing_events,
    result_self_state_events,
    result_timeline_coverage,
    result_total_damage,
)
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario

#: A spread wide enough to reach an ability kit, an auto kit, a self-healer
#: and a resourceless one, and small enough to stay a unit test.
CHAMPIONS = ("Ahri", "Jinx", "Aatrox", "Garen", "Soraka", "Yasuo")

READERS = {
    "damage_events": result_damage_events,
    "cast_timeline": result_cast_timeline,
    "self_healing_events": result_self_healing_events,
    "self_state_events": result_self_state_events,
    "keystone_state_events": result_keystone_state_events,
    "breakdown": result_breakdown,
    "total_damage": result_total_damage,
    "timeline_coverage": result_timeline_coverage,
    "keystone": result_keystone,
}

RESULT = {
    "damage_events": [],
    "cast_timeline": [],
    "self_healing_events": [],
    "self_state_events": [],
    "keystone_state_events": [],
    "breakdown": {},
    "total_damage": 1200.0,
    "timeline_coverage": {"complete": True},
    "keystone": "Conqueror",
}


def _fight(champion: str, *, score_only: bool) -> dict:
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": 13,
            "role": "mid",
            "items": [],
            "enemies": [{"champion": "Aatrox", "level": 13, "role": "top"}],
        },
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    params = replace(resolved.fight_params, fight_duration_seconds=10.0)
    return run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        params,
        score_only=score_only,
    )


@pytest.fixture(name="results", scope="module")
def _results() -> list[dict]:
    return [
        _fight(champion, score_only=score_only)
        for champion in CHAMPIONS
        for score_only in (False, True)
    ]


class TestTheRequiredSetIsMeasured:
    def test_every_declared_key_is_on_every_result(self, results):
        for field in FIGHT_RESULT_REQUIRED_FIELDS:
            absent = [index for index, row in enumerate(results) if field not in row]
            assert absent == [], f"{field} is absent from results {absent}"

    def test_the_scoring_mode_really_does_drop_keys(self, results):
        """Named because the whole point of the intersection is that the two
        modes differ; a mode that dropped nothing would make it vacuous."""
        full, scored = results[0], results[1]
        assert set(full) - set(scored) >= {"target_ending_health", "damage_by_type"}

    def test_no_other_key_survives_both_modes_unclaimed(self, results):
        """A key on every result of both modes belongs in the declared set or
        in a reader that states why it is left out."""
        universal = set(results[0]).intersection(*results[1:])
        assert universal - set(FIGHT_RESULT_REQUIRED_FIELDS) == {
            "auto_attack_policy",
            "auto_attack_schedule",
            "champion_stats",
            "control_events",
            "effective_armor",
            "effective_mr",
            "item_state_receipts",
            "notes",
            "phantom_hit_autos",
            "phantom_hit_count",
            "resource_ledger",
            "resource_remaining",
            "resource_restore_events",
            "resource_spent",
            "rotation",
        }


class TestTheReadersRefuseAnAbsentRequiredKey:
    @pytest.mark.parametrize(("field", "reader"), sorted(READERS.items()))
    def test_each_reader_raises_and_names_its_field(self, field, reader):
        result = {key: value for key, value in RESULT.items() if key != field}
        with pytest.raises(ValueError, match=field):
            reader(result)

    def test_a_stamped_result_reads_its_own_values(self):
        assert result_total_damage(RESULT) == 1200.0
        assert result_keystone(RESULT) == "Conqueror"
        assert result_timeline_coverage(RESULT) == {"complete": True}
        assert result_breakdown(RESULT) == {}

    def test_an_empty_stream_is_a_reading_and_not_an_absence(self):
        """A fight that placed no cast publishes an empty list, which is the
        answer, and a result missing the key is a producer break."""
        assert result_cast_timeline(RESULT) == []
