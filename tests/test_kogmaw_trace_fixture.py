"""The pinned Kog'Maw fight, line by line, with every line explained.

The fixture is `tests/fixtures/kogmaw_dusk_and_dawn_trace.json`, regenerated
by `python scripts/fight_trace.py <request.json> --capture <fixture>` and
never hand-edited: it carries the request beside the trace, so the assertions
below re-run that request and compare rather than describing it.
"""

import json
from pathlib import Path

import pytest

from src.calculator import trigger_stream
from src.calculator.calculate import calculate_payload
from src.calculator.fight.ledger.trace import NO_RAW_PUBLISHED, NO_STEP_MEASURED
from src.calculator.fight.results import CHAMPION_PRODUCER_PREFIX
from src.calculator.item_behavior_catalog import behavior_rules
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario
from src.calculator.survival.pricing import NO_RESISTANCE_PUBLISHED

FIXTURE = Path(__file__).parent / "fixtures" / "kogmaw_dusk_and_dawn_trace.json"

#: The one fight in the fixture: a manual target, so one trace.
TRACE_NAME = "manual target"

#: How many lines each source authors, and so the whole fight: ten swings,
#: their ten ability-carried on-hits, three spellblade procs with the three
#: doubled applications they consume, and the four ability casts.
LINES_PER_SOURCE = {
    "Q": 2,
    "E": 1,
    "R": 1,
    "auto_attacks": 10,
    "on_hit_ability_W": 10,
    "spellblade_Dusk and Dawn": 3,
    "double_on_hit_Dusk and Dawn": 3,
}

#: The step that authors each source's packets, measured while the fight ran.
STEP_PER_SOURCE = {
    "Q": "fight.rotation.ability_rotation._compute_ability_rotation",
    "E": "fight.rotation.ability_rotation._compute_ability_rotation",
    "R": "fight.rotation.ability_rotation._compute_ability_rotation",
    "auto_attacks": "fight.autos.simulation._simulate_auto_attacks",
    "on_hit_ability_W": "fight.autos.on_hit_layering._layer_on_hit_effects",
    "spellblade_Dusk and Dawn": "fight.autos.spellblade._add_spellblade_damage",
    "double_on_hit_Dusk and Dawn": "fight.autos.spellblade._add_spellblade_damage",
}

#: Every source states every fact: the raw its step priced the packet from,
#: and the resistance that step mitigated against.  Each row is here so a
#: family that stops stating one names itself rather than vanishing from a set.
REFUSALS_PER_SOURCE = {
    "Q": [],
    "E": [],
    "R": [],
    "auto_attacks": [],
    "on_hit_ability_W": [],
    "spellblade_Dusk and Dawn": [],
    "double_on_hit_Dusk and Dawn": [],
}

#: The resistance each source's packets met.  Kog'Maw Q is priced against the
#: MR it goes on to shred, so its casts meet 100 in a fight whose published
#: effective MR is 75.3333: two numbers for one fight, each stated by the site
#: that applied it rather than back-computed from a mitigated amount.
RESISTANCE_PER_SOURCE = {
    "Q": 100.0,
    "E": 75.33333333333334,
    "R": 75.33333333333334,
    "auto_attacks": 75.33333333333334,
    "on_hit_ability_W": 75.33333333333334,
    "spellblade_Dusk and Dawn": 75.33333333333334,
    "double_on_hit_Dusk and Dawn": 75.33333333333334,
}


@pytest.fixture(name="fixture", scope="module")
def _fixture() -> dict:
    """The committed capture: the request, and the trace it produced."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(name="trace", scope="module")
def _trace(fixture) -> dict:
    """The fight's own lines, as the fixture holds them."""
    return fixture["traces"][TRACE_NAME]


def test_the_fixture_reproduces_from_its_own_request(fixture, trace):
    """A capture, not a description: the request in it produces the trace in it."""
    payload = calculate_payload(fixture["request"], deterministic=True, trace=True)
    assert payload["trace"] == trace


def test_every_packet_of_the_fight_is_one_line(trace):
    """The lines account for the whole fight, to the cent."""
    counted: dict[str, int] = {}
    for line in trace["lines"]:
        counted[line["source"]] = counted.get(line["source"], 0) + 1
    assert counted == LINES_PER_SOURCE
    assert len(trace["lines"]) == sum(LINES_PER_SOURCE.values())
    assert round(sum(line["mitigated"] for line in trace["lines"]), 4) == 1934.3695


def test_every_line_names_the_step_that_wrote_it(trace):
    """Measured while the fight ran, so a moved band moves this table."""
    for line in trace["lines"]:
        assert line["step"] == STEP_PER_SOURCE[line["source"]]
        assert NO_STEP_MEASURED not in line["refusals"]


def test_every_line_states_its_facts_or_names_the_refusal(trace):
    """No line is silently short of a fact: what is missing is named."""
    for line in trace["lines"]:
        assert sorted(line["refusals"]) == sorted(
            REFUSALS_PER_SOURCE[line["source"]]
        ), line["source"]
        assert (line["raw"] is None) == (NO_RAW_PUBLISHED in line["refusals"])
        assert line["resistance_met"] is not None
        assert NO_RESISTANCE_PUBLISHED not in line["refusals"]


def test_every_line_states_the_resistance_it_met(trace):
    """Read off the mitigation site, so a shred window is visible as one.

    The fight publishes 75.3333 effective MR, which is what every packet
    after Kog'Maw Q's shred met; Q's own casts met the 100 they shredded.
    """
    for line in trace["lines"]:
        assert line["resistance_met"] == RESISTANCE_PER_SOURCE[line["source"]], line[
            "source"
        ]
    assert RESISTANCE_PER_SOURCE["E"] == trace["effective_mr"]
    assert RESISTANCE_PER_SOURCE["auto_attacks"] == trace["effective_armor"]
    assert RESISTANCE_PER_SOURCE["Q"] > trace["effective_mr"]


def test_every_stated_raw_prices_its_own_mitigated_amount(trace):
    """`raw * 100 / (100 + resistance_met)` on every line, with no amp term."""
    priced = 0
    for line in trace["lines"]:
        if line["raw"] is None or line["damage_class"] == "true":
            continue
        priced += 1
        assert line["mitigated"] == pytest.approx(
            line["raw"] * 100 / (100 + line["resistance_met"])
        ), line["source"]
    assert priced == len(trace["lines"]) == 30


def test_an_items_traced_mechanics_are_the_rules_it_declares(trace):
    """Three Dusk and Dawn rows, one declared rule, and no second name.

    The doubled application states no mechanic of its own: it is a sum over
    the producers of one on-hit application, which is the one shape a
    declaration cannot carry, so its attribution rides the row's
    `on_hit_shares` receipt instead of this column.
    """
    traced = {
        line["mechanic"]
        for line in trace["lines"]
        if "Dusk and Dawn" in line["source"] and line["mechanic"]
    }
    declared = {
        rule.mechanic_id
        for rule in behavior_rules("Dusk and Dawn")
        if rule.mechanic_id in trigger_stream.CAPABILITIES
    }
    assert traced == declared == {"dusk_and_dawn.spellblade"}
    unnamed = {line["source"] for line in trace["lines"] if not line["mechanic"]} & {
        "double_on_hit_Dusk and Dawn"
    }
    assert unnamed == {"double_on_hit_Dusk and Dawn"}


def test_the_champion_rider_names_the_slot_that_carries_it(trace):
    """The mechanic column's other vocabulary, on the one row that uses it.

    A champion's on-hit magnitude is its module's, so the rider names the
    slot behind the champion prefix rather than an item rule id.
    """
    assert {
        line["source"]: line["mechanic"]
        for line in trace["lines"]
        if line["mechanic"].startswith(CHAMPION_PRODUCER_PREFIX)
    } == {"on_hit_ability_W": f"{CHAMPION_PRODUCER_PREFIX}W"}


def test_the_doubled_application_names_its_producers_on_the_row(fixture):
    """The attribution the traced column cannot carry, on the row that sums it."""
    request = parse_scenario_request(fixture["request"], deterministic=True)
    resolved = resolve_scenario(request)
    result = run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        resolved.fight_params,
    )
    row = result["breakdown"]["double_on_hit_Dusk and Dawn"]
    assert [share["producer"] for share in row["on_hit_shares"]] == ["champion:W"]
    assert sum(share["damage"] for share in row["on_hit_shares"]) == pytest.approx(
        row["total_damage"]
    )
    published = calculate_payload(fixture["request"], deterministic=True)
    assert "on_hit_shares" not in published["breakdown"]["double_on_hit_Dusk and Dawn"]
