"""Phase 4 S5: the declared adequacy conditions behind two narrowed results.

Two halves.  The structural half pins the module's four tables against each
other — every condition declared once, probed once, and the one clause both
gates read being literally one function.  The behavioural half drives twelve
fights and asserts the ledger each one *returned* is the projection its
declared conditions chose, with a coverage test proving every condition fires
somewhere in the matrix so no clause is agreeing by never running.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.calculator import damage as damage_module
from src.calculator import ledger_projection as lp
from src.calculator import pipeline as pipeline_module
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.healing import (
    HEALING_RULE_CHAMPIONS,
    SELF_HEAL_RULE_SLOT,
    self_heal_rule_owner,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.trigger_stream import (
    ChampionSlotOwner,
    EngineOwner,
    ItemOwner,
    pair_outcome_items,
    tuple_incapable_items,
)

C = lp.AdequacyCondition

# One fight per condition, plus the plain build that must stay on the light
# tuple ledger.  ``fires`` is the conditions this row is *expected* to raise;
# a row may raise more (a real item rarely does exactly one thing), which is
# why the coverage assertion is over the union rather than per row.
MATRIX: tuple[
    tuple[str, str, tuple[str, ...], str, float, tuple[lp.AdequacyCondition, ...]], ...
] = (
    ("plain", "Annie", ("Luden's Echo",), "", 0.0, ()),
    (
        "threshold_heal",
        "Annie",
        ("Luden's Echo",),
        "",
        250.0,
        (C.TARGET_THRESHOLD_HEAL,),
    ),
    ("healing_rule", "Aatrox", (), "", 0.0, (C.CHAMPION_SELF_HEAL_RULE,)),
    ("item_heal", "Annie", ("Sundered Sky",), "", 0.0, (C.ITEM_SELF_HEAL_PACKETS,)),
    ("item_regen", "Annie", ("Crystalline Bracer",), "", 0.0, (C.ITEM_HEALTH_REGEN,)),
    ("lifesteal", "Annie", ("Bloodthirster",), "", 0.0, (C.LIFESTEAL_STAT,)),
    ("omnivamp", "Annie", ("Hextech Gunblade",), "", 0.0, (C.OMNIVAMP_STAT,)),
    ("saturating", "Malphite", ("Riftmaker",), "", 0.0, (C.SATURATING_OMNIVAMP,)),
    ("keystone_heal", "Annie", (), "Conqueror", 0.0, (C.KEYSTONE_SELF_HEAL,)),
    ("empowered_auto", "Jax", (), "", 0.0, (C.EMPOWERED_BASIC_ATTACK,)),
    ("raw_stream", "Annie", ("Imperial Mandate",), "", 0.0, (C.RAW_ROW_STREAM_HOLDER,)),
    ("execute", "Annie", ("The Collector",), "", 0.0, (C.EXECUTE_THRESHOLD_STAMP,)),
    ("interaction", "Malphite", (), "", 0.0, (C.ORDERED_INTERACTION_METADATA,)),
    ("self_shield", "Annie", ("Eclipse",), "", 0.0, (C.SELF_SHIELD_PROC,)),
    ("pair_outcome", "Annie", ("Cryptbloom",), "", 0.0, (C.PAIR_OUTCOME_STREAM,)),
)


def _params(threshold_heal: float, keystone: str = "") -> FightParams:
    """A timed score-only fight, long enough for a ramp-armed grant to arm."""
    request: dict[str, object] = {"fight_mode": "timed", "fight_duration": 8}
    if keystone:
        request["keystone"] = keystone
    params = FightParams.from_request(request, deterministic=True)
    if not threshold_heal:
        return params
    return replace(
        params,
        target_threshold_health_heal=threshold_heal,
        target_threshold_health_ratio=0.3,
        target_threshold_health_duration=5.0,
    )


def _inputs(
    champion: str,
    item_names: tuple[str, ...],
    threshold_heal: float,
    keystone: str = "",
):
    """The two input records one matrix row resolves to, live off ``run_fight``.

    Captured through the engines' own builders rather than assembled here, so
    a field the projection reads and the fight fills differently would fail
    rather than be reproduced by the fixture.  ``result`` is the fight the
    same inputs produced, which is what pins the projection to the ledger the
    caller actually received.
    """
    captured: dict[str, object] = {}
    real_ledger_inputs = pipeline_module.ledger_inputs
    real_shield_inputs = damage_module.shield_outcome_inputs

    def spy_ledger(params, champion_data, items, effects, stats, abilities):
        captured["ledger"] = real_ledger_inputs(
            params, champion_data, items, effects, stats, abilities
        )
        return captured["ledger"]

    def spy_shield(config, items):
        captured["shield"] = real_shield_inputs(config, items)
        return captured["shield"]

    pipeline_module.ledger_inputs = spy_ledger
    damage_module.shield_outcome_inputs = spy_shield
    try:
        captured["result"] = run_fight(
            get_champion(champion),
            18,
            [get_item_by_name(name) for name in item_names],
            _params(threshold_heal, keystone),
            score_only=True,
        )
    finally:
        pipeline_module.ledger_inputs = real_ledger_inputs
        damage_module.shield_outcome_inputs = real_shield_inputs
    return captured


# ── structure ───────────────────────────────────────────────────────────────


def test_every_condition_is_declared_and_probed_exactly_once():
    """The import-time validation's claim, restated as a test that can fail."""
    assert set(lp.DECLARATIONS) == set(C)
    probed = list(lp.LEDGER_CONDITIONS) + list(lp.SHIELD_OUTCOME_CONDITIONS)
    assert set(probed) == set(C)
    # Thirteen ledger clauses — D-38's ten plus the keystone self-heal, the
    # ordered interaction metadata and the self-shield proc — and two
    # shield-outcome ones, sharing one, so the fifteen probe slots cover
    # fourteen distinct conditions.
    assert len(lp.LEDGER_CONDITIONS) == 13
    assert len(lp.SHIELD_OUTCOME_CONDITIONS) == 2
    assert len(probed) == len(set(probed)) + 1


def test_the_two_gates_share_exactly_the_threshold_heal_clause():
    """Criterion 15's mirror: one condition, one function, two call sites."""
    shared = set(lp.LEDGER_CONDITIONS) & set(lp.SHIELD_OUTCOME_CONDITIONS)
    assert shared == {C.TARGET_THRESHOLD_HEAL}


def test_each_projection_declares_what_it_cannot_serve():
    """Totality over the projection enum, with the wide members serving all."""
    assert lp.unserved_conditions(lp.ResultProjection.DICT_ROW_LEDGER) == frozenset()
    assert (
        lp.unserved_conditions(lp.ResultProjection.RESOLVED_SHIELD_OUTCOME)
        == frozenset()
    )
    assert lp.unserved_conditions(lp.ResultProjection.LIGHT_TUPLE_LEDGER) == frozenset(
        lp.LEDGER_CONDITIONS
    )
    assert lp.unserved_conditions(
        lp.ResultProjection.SKIPPED_SHIELD_OUTCOME
    ) == frozenset(lp.SHIELD_OUTCOME_CONDITIONS)


def test_requires_fields_names_exactly_the_stat_derived_conditions():
    """``requires_fields`` is the stat-derived half of criterion 15."""
    declared = {
        condition: declaration.requires_fields
        for condition, declaration in lp.DECLARATIONS.items()
        if declaration.requires_fields
    }
    assert declared == {
        C.ITEM_HEALTH_REGEN: frozenset(
            {"health_regen_per_five", "base_health_regen_per_five"}
        ),
        C.LIFESTEAL_STAT: frozenset({"lifesteal_percent"}),
        C.OMNIVAMP_STAT: frozenset({"omnivamp_percent"}),
    }


def test_a_probe_cannot_read_a_stat_its_condition_did_not_declare():
    """``requires_fields`` is load-bearing, not a comment beside the probe."""
    inputs = _inputs("Annie", ("Luden's Echo",), 0.0)["ledger"]
    assert inputs.raw_stat(C.LIFESTEAL_STAT, "lifesteal_percent") == 0.0
    with pytest.raises(lp.UndeclaredStatRead):
        inputs.raw_stat(C.LIFESTEAL_STAT, "omnivamp_percent")


def test_the_healing_registry_owns_every_declaring_champion():
    """``HEALING_RULE_CHAMPIONS`` as owners, item for item (criterion 15)."""
    owned = {
        name: self_heal_rule_owner(name)
        for name in HEALING_RULE_CHAMPIONS | {"Annie", "Jax"}
    }
    assert {name for name, owner in owned.items() if owner is not None} == set(
        HEALING_RULE_CHAMPIONS
    )
    assert owned["Aatrox"] == ChampionSlotOwner("Aatrox", SELF_HEAL_RULE_SLOT)
    assert owned["Annie"] is None


# ── the projection the fight actually took ──────────────────────────────────


@pytest.mark.parametrize(
    ("label", "champion", "item_names", "keystone", "threshold_heal", "fires"),
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
# comment-ok: width - a pylint pragma cannot wrap
def test_the_fight_returns_the_projection_the_conditions_chose(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    label, champion, item_names, keystone, threshold_heal, fires
):
    """The gate's answer *is* the projection, on every matrix row.

    ``damage_events_tuple`` is the engine's own statement of which ledger
    shape it returned, so asserting it against the derivation pins the flip
    to the result the caller received rather than to the predicate's return
    value — the two would agree even if the call site had been rewired to
    something else.
    """
    captured = _inputs(champion, item_names, threshold_heal, keystone)
    ledger_inputs = captured["ledger"]
    shield_inputs = captured["shield"]

    derived_light = (
        lp.ledger_projection(ledger_inputs) is lp.ResultProjection.LIGHT_TUPLE_LEDGER
    )
    assert bool(captured["result"].get("damage_events_tuple")) == derived_light, label
    assert all(
        isinstance(event, dict) is not derived_light
        for event in captured["result"]["damage_events"]
    ), label

    raised = {demand.condition for demand in lp.ledger_demands(ledger_inputs)} | {
        demand.condition for demand in lp.shield_outcome_demands(shield_inputs)
    }
    assert set(fires) <= raised, label


def test_the_matrix_raises_every_declared_condition():
    """The projection choice is not vacuous: each condition fires somewhere."""
    raised: set[lp.AdequacyCondition] = set()
    for _label, champion, item_names, keystone, threshold_heal, _fires in MATRIX:
        captured = _inputs(champion, item_names, threshold_heal, keystone)
        raised |= {demand.condition for demand in lp.ledger_demands(captured["ledger"])}
        raised |= {
            demand.condition for demand in lp.shield_outcome_demands(captured["shield"])
        }
    assert raised == set(C)


# ── receipts ────────────────────────────────────────────────────────────────


def test_a_starved_reader_is_named_not_merely_counted():
    """A demand carries who owns the mechanic and what would have read it."""
    captured = _inputs("Aatrox", ("Imperial Mandate",), 0.0)
    demands = {
        demand.condition: demand for demand in lp.ledger_demands(captured["ledger"])
    }

    champion = demands[C.CHAMPION_SELF_HEAL_RULE]
    assert champion.owner == ChampionSlotOwner("Aatrox", SELF_HEAL_RULE_SLOT)
    assert champion.reader == "healing.derive_self_healing"

    holder = demands[C.RAW_ROW_STREAM_HOLDER]
    assert holder.owner == ItemOwner("Imperial Mandate")
    assert "Imperial Mandate" in tuple_incapable_items()
    assert holder.reason


def test_the_shield_outcome_names_its_takedown_holder():
    """Cryptbloom's stream is synthesized from the outcome, so it keeps it."""
    captured = _inputs("Annie", ("Cryptbloom",), 0.0)
    demands = lp.shield_outcome_demands(captured["shield"])

    assert [demand.condition for demand in demands] == [C.PAIR_OUTCOME_STREAM]
    assert demands[0].owner == ItemOwner("Cryptbloom")
    assert pair_outcome_items() == frozenset({"Cryptbloom"})


def test_a_two_holder_build_names_both_holders():
    """``holders_in`` answered yes; the demand list answers who."""
    captured = _inputs("Annie", ("Imperial Mandate", "Black Cleaver"), 0.0)
    holders = [
        demand.owner
        for demand in lp.ledger_demands(captured["ledger"])
        if demand.condition is C.RAW_ROW_STREAM_HOLDER
    ]

    assert holders == [ItemOwner("Imperial Mandate"), ItemOwner("Black Cleaver")]


def test_an_engine_owned_condition_names_the_deriving_function():
    """No item owns life steal, so the receipt names the code that reads it."""
    captured = _inputs("Annie", ("Bloodthirster",), 0.0)
    demands = {
        demand.condition: demand for demand in lp.ledger_demands(captured["ledger"])
    }

    assert demands[C.LIFESTEAL_STAT].owner == EngineOwner(
        "damage._add_lifesteal_events"
    )
