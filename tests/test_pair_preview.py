"""A pair-engine preview is published, and never summed (D-62).

Bloodsong's Expose Weakness was the campaign's one frozen
``DivergenceReceipt``: the pair engine amplified one coarse row once for the
whole fight, the walk armed a timed modifier per spellblade proc, and neither
was named the answer.  Phase 4 S7 named one.  The pool of amplified damage is
every roster attacker's damage inside a live window on one enemy — a roster
input — so the walk owns the mechanic, prices the holder's own packets like
everyone else's, and the pair reading survives as a declared ``THEORETICAL``
preview.

A preview is not a deletion and not a rival.  It is still the honest answer
to "what would one attacker alone have done", so it is still published where
that question is asked; what it may never do is enter a roster total beside
the number the walk delivered, because that is one mechanic counted twice
with no symptom.  This file is both halves.
"""

from __future__ import annotations

from functools import lru_cache

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.program.build import (
    dropped_preview_mechanics,
    pair_preview_mechanics,
    walk_repriced_mechanics,
)
from src.calculator.stats import calculate_total_stats
from src.calculator.program.compile import WalkCompiler
from src.calculator.survival.actions import EVENT_SLOTS
from src.calculator.trigger_stream import CAPABILITIES, Authority, Engine
from src.calculator.program.views import ViewTag

HOLDER = "Jax"
ALLY = "Lulu"
ENEMY = "Aatrox"
EXPOSE = "Bloodsong — Expose Weakness"
PREVIEW_ROW_PREFIX = "expose_weakness_"


@lru_cache(maxsize=2)
def _roster(items):
    """One roster response through the public request path."""
    payload = {
        "champion": HOLDER,
        "level": 18,
        "items": list(items),
        "role": "support",
        "role_quest_complete": True,
        "fight_mode": "time_based",
        "fight_duration": 8,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "enemies": [{"champion": ENEMY, "level": 18, "items": []}],
        "allies": [
            {
                "champion": ALLY,
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()


def _outgoing(body, participant_id):
    """One participant's coupled outgoing total."""
    row = next(
        row
        for row in body["combat"]["breakdown"]
        if row["participant_id"] == participant_id
    )
    return row["total_damage"]


def _amped(body, attacker):
    """That attacker's coupled events carrying Expose Weakness's multiplier."""
    return [
        event
        for event in body["combat"]["events"]
        if event.get("attacker") == attacker
        and (event.get("support_damage_multiplier") or {}).get("source") == EXPOSE
    ]


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


def test_the_walk_owns_the_mechanic_and_the_pair_half_previews_it():
    """One mechanic, one authority, and two halves that agree about it."""
    walk = CAPABILITIES["bloodsong.expose_weakness"]
    pair = CAPABILITIES[walk.pair_of]
    assert walk.authority is Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW
    assert pair.authority is walk.authority
    assert walk.view_tags[Engine.WALK] is ViewTag.APPLIED
    assert pair.view_tags[Engine.PAIR] is ViewTag.THEORETICAL
    assert walk.divergence_ref is None


def test_both_spellings_of_the_previewed_mechanic_resolve():
    """The join is by mechanic id, and the two halves spell it differently.

    The pair engine stamps its row with the id its declared *rule* carries —
    the walk half's — while the registry declares the tag on the *pair*
    half.  A set holding only one of the two would silently stop excluding.
    """
    previewed = pair_preview_mechanics()
    assert "bloodsong.expose_weakness" in previewed
    assert "bloodsong.expose_weakness_preview" in previewed


# ---------------------------------------------------------------------------
# The number
# ---------------------------------------------------------------------------


def test_the_holder_is_amplified_by_the_walk_like_every_other_attacker():
    """The correction itself: no owner skip, so the holder is priced too.

    Under the retired ``SPLIT`` reading the walk skipped the holder and the
    pair engine priced him on a different schedule.  The walk now prices
    everyone, so the holder's own packets carry the same multiplier the
    ally's do.
    """
    body = _roster(("Bloodsong",))
    holder = _amped(body, "main")
    assert holder, "the holder's own packets are amplified by the walk"
    assert {
        round(event["support_damage_multiplier"]["multiplier"], 4) for event in holder
    } == {1.08}


def test_the_pair_preview_is_absent_from_every_roster_total():
    """No ``expose_weakness_*`` row or event reaches the coupled composition.

    This is the double count the authority move closes: the walk's number
    and the pair engine's preview of it were both in one roster total.
    """
    body = _roster(("Bloodsong",))
    sources = {str(event.get("source", "")) for event in body["combat"]["events"]}
    assert not any(source.startswith(PREVIEW_ROW_PREFIX) for source in sources)
    rows = {
        str(source.get("name", ""))
        for row in body["combat"]["breakdown"]
        for source in row.get("sources", ())
    }
    assert "Bloodsong (Expose Weakness)" not in rows


def test_the_amplification_is_the_walk_s_alone_and_not_the_preview_s():
    """The applied total is the coupled contribution alone.

    Re-derived rather than pinned: the holder's amplified events are the
    walk's own rows, so their bonus is exactly the sum of each amplified
    row's pre-multiplier damage times the declared rate.  The pair preview's
    figure is a different number computed a different way, and it is not in
    here.
    """
    body = _roster(("Bloodsong",))
    amped = _amped(body, "main")
    bonus = sum(
        event["damage"]
        - event["damage"] / event["support_damage_multiplier"]["multiplier"]
        for event in amped
    )
    assert bonus > 0.0
    control = _outgoing(_roster(()), "main")
    assert _outgoing(body, "main") > control


def test_removing_the_item_removes_the_amplification_entirely():
    """Zero, and not the preview, is what a missing coupled half leaves.

    The control run holds no Bloodsong at all, so nothing amplifies and
    nothing falls back to a pair-authored figure.  A slice that deleted the
    coupled interpreter and left the preview standing would fail here on a
    number rather than on a structural claim.
    """
    body = _roster(())
    assert _amped(body, "main") == []
    assert _amped(body, "ally1") == []


def _one_dropped_preview_mechanic():
    """A previewed mechanic whose row a roster composition drops whole.

    Not merely *any* ``THEORETICAL`` mechanic, and the difference is the
    subject of the two cases below: a rider-delivered preview is a second
    copy of a number the walk authors elsewhere and its row leaves the
    composition entirely, while a retired family's preview is the packet the
    walk is about to price from its own declaration and its row survives
    carrying that declaration.  Reading the difference off
    :func:`walk_repriced_mechanics` rather than naming a mechanic is what
    keeps these cases pointed at dropping the day another family retires.
    """
    dropped = sorted(pair_preview_mechanics() - walk_repriced_mechanics())
    assert dropped, "the registry declares no dropped pair preview to exclude"
    return dropped[0]


def _engine_result_with_a_preview_row():
    """One pair fight holding a previewed row between two delivered ones."""
    return {
        "breakdown": {
            "Q": {"total_damage": 100.0},
            "preview_row": {
                "total_damage": 40.0,
                "pair_preview_of": _one_dropped_preview_mechanic(),
            },
            "W": {"total_damage": 60.0},
        },
        "damage_events": [
            {
                "time": 0.0,
                "sequence": 0,
                "source_key": "Q",
                "damage_type": "magic",
                "damage": 100.0,
            },
            {
                "time": 1.0,
                "sequence": 1,
                "source_key": "preview_row",
                "damage_type": "magic",
                "damage": 40.0,
            },
            {
                "time": 2.0,
                "sequence": 2,
                "source_key": "W",
                "damage_type": "magic",
                "damage": 60.0,
            },
        ],
        "self_healing_events": [],
        "timeline_coverage": {},
    }


def _compile_engine_result():
    """The score path's composition of that fight, as typed actions."""
    compiler = WalkCompiler(0)
    compiler.add_engine_result(
        _engine_result_with_a_preview_row(),
        "main",
        0,
        "enemy:Aatrox",
        1,
        {},
        8.0,
        {},
        [],
    )
    return compiler.actions


def test_the_score_path_drops_the_previews_the_receipt_path_drops():
    """One compiler, so one answer about which rows a roster composes.

    The score path compiles a candidate's fresh pair fights straight from
    the engine rows, and it is the surface that picks the optimizer's
    winner.  A preview summed here is the walk's number and a preview of it
    inside one score, with nothing in the response saying so.
    """
    sources = [action.source_key for action in _compile_engine_result()]
    assert sources == ["Q", "W"]


def test_dropping_a_preview_does_not_renumber_the_events_after_it():
    """The surviving ids stay positional, exactly as on the receipt path.

    Event ids are the row's index in the engine's own ledger, so filtering
    rather than skipping in place would move every public id downstream of
    the first preview — and those ids are what trigger links, heal linkage
    and the corpus receipts are keyed by.
    """
    slots = [action.event_slot for action in _compile_engine_result()]
    texts = [EVENT_SLOTS.text(slot) for slot in slots]
    assert texts == ["main:enemy:Aatrox:0", "main:enemy:Aatrox:2"]


def test_the_retired_routing_family_has_no_preview_to_double_count() -> None:
    """D-62's uniqueness for ``damage_routing``, which is an emptiness.

    Every other retirement so far had two halves to keep apart: a pair row
    stamped ``THEORETICAL`` and a walk number stamped ``APPLIED``, with D-62's
    one-``APPLIED``-per-``(mechanic, subject, event_id)`` rule holding the
    line between them.  The triage measured this family authoring no priced
    pair row at all, so the half that could be double-counted does not exist,
    and umbrella Amendment P discharges that half as an enumerated emptiness.

    An emptiness is only worth anything while somebody checks it is still
    empty, which is what this is.  Three claims: no declaration of the family
    is a previewed mechanic, none of them is re-priced by the walk's pricer
    either -- they are riders and state adjustments, not prices -- and every
    one of their walk halves is ``APPLIED`` and rider-delivered.  A future
    mechanic of the family that authored a pair row would have to declare a
    preview to be honest, and it would fail here rather than quietly summing
    beside the rider the walk already stages.
    """
    routing = {
        "deaths_dance.ignore_pain",
        "serpents_fang.shield_bypass",
        "the_collector.execute",
    }
    assert not routing & pair_preview_mechanics()
    assert not routing & walk_repriced_mechanics()
    for mechanic in sorted(routing):
        capability = CAPABILITIES[mechanic]
        assert capability.engine is Engine.WALK, mechanic
        assert capability.view_tags[Engine.WALK] is ViewTag.APPLIED, mechanic
        assert type(capability.packet_source).__name__ == "RiderDelivery", mechanic
        assert f"{mechanic}_preview" not in CAPABILITIES, mechanic


def test_the_retired_shred_family_has_no_preview_to_double_count() -> None:
    """D-62's uniqueness for ``resistance_shred``, which is an emptiness too.

    The second family to retire with nothing to keep apart, and it gets there
    a different way from ``damage_routing``.  A shred is not damage at all: it
    moves the TARGET's resistance before penetration is applied, so it authors
    no priced pair row -- the triage measured exactly that -- and the walk's
    pricer never sees it either, because there is no packet of this family for
    a ``DeclaredPacket`` to be.

    Four claims, and the fourth is the one this shape needs that the routing
    family's did not.  Neither declaration is a previewed mechanic; neither is
    re-priced by the walk's pricer; each is the ``APPLIED`` pair-local half of
    a ``SPLIT`` with no ``_preview`` twin, which is what says the pair engine
    still owns its own reading under H1; and each has a walk-side half that
    names it through ``pair_of`` and delivers a packet -- the cross-participant
    term umbrella Amendment O, Ruling 2 required this family to have named
    before it could retire.  A future mechanic of the family that authored a
    pair row would have to declare a preview to be honest, and it would fail
    here rather than quietly summing beside the reduction the walk stages.
    """
    shreds = {
        "black_cleaver.armor_reduction": "black_cleaver.carve",
        "bloodletters_curse.mr_reduction": "bloodletters_curse.vile_decay",
    }
    assert not set(shreds) & pair_preview_mechanics()
    assert not set(shreds) & walk_repriced_mechanics()
    for mechanic, partner in sorted(shreds.items()):
        capability = CAPABILITIES[mechanic]
        assert capability.engine is Engine.PAIR, mechanic
        assert capability.view_tags[Engine.PAIR] is ViewTag.APPLIED, mechanic
        assert capability.authority is Authority.SPLIT, mechanic
        assert f"{mechanic}_preview" not in CAPABILITIES, mechanic
        walk = CAPABILITIES[partner]
        assert walk.engine is Engine.WALK, partner
        assert walk.view_tags[Engine.WALK] is ViewTag.APPLIED, partner
        assert walk.pair_of == mechanic, partner
        assert isinstance(walk.packet_source, str) and walk.packet_source, partner


# ---------------------------------------------------------------------------
# A preview a composition drops is not computed in the first place
# ---------------------------------------------------------------------------

CINDERBLOOM = "shadowflame.cinderbloom"
SHADOWFLAME_ROW = "shadowflame_Shadowflame"
BURN_ROW = "burn_Liandry's Torment"


def _engine_fight(*, roster_composed: bool):
    """Ahri holding Shadowflame and Liandry's, against a lifelined target.

    The lifeline is what makes the ordered shield walk do its other job: the
    Liandry max-health reprice, which is the burn's own damage and survives a
    composition. One build exercises both halves of the one walk.
    """
    champion = get_champion("Ahri")
    items = [get_item_by_name("Shadowflame"), get_item_by_name("Liandry's Torment")]
    stats = calculate_total_stats(champion, 18, items)
    abilities = parse_champion_abilities(
        champion, 18, stats["ability_power"], champion_stats=stats
    )
    return calculate_fight_damage(
        dict(stats),
        abilities,
        items,
        FightConfig(
            target_health=2000.0,
            target_armor=60.0,
            target_magic_resistance=60.0,
            fight_duration_seconds=8.0,
            deterministic=True,
            auto_attack_uptime=1.0,
            target_threshold_health_bonus=800.0,
            target_threshold_health_heal=600.0,
            target_threshold_health_ratio=0.35,
            target_threshold_health_duration=4.0,
            roster_composed=roster_composed,
        ),
    )


def test_cinderbloom_is_a_preview_the_composition_drops():
    """The declaration the skip below reads, rather than an item name."""
    assert CINDERBLOOM in dropped_preview_mechanics()
    assert CINDERBLOOM not in walk_repriced_mechanics()


def test_a_composed_fight_runs_the_reprice_half_of_the_walk_alone():
    """No Cinderbloom row, and the Liandry reprice unchanged to the cent."""
    solo = _engine_fight(roster_composed=False)
    composed = _engine_fight(roster_composed=True)

    assert solo["breakdown"][SHADOWFLAME_ROW]["total_damage"] > 0.0
    assert SHADOWFLAME_ROW not in composed["breakdown"]
    assert (
        composed["breakdown"][BURN_ROW]["total_damage"]
        == solo["breakdown"][BURN_ROW]["total_damage"]
    )
    # More than the row leaves: the holder's own whole-total amp no longer
    # levies a share on a number the composition throws away.
    dropped = solo["breakdown"][SHADOWFLAME_ROW]["total_damage"]
    assert solo["total_damage"] - composed["total_damage"] > dropped


def test_the_single_attacker_surface_still_publishes_the_preview():
    """A roster response's own main fight is the question the preview answers."""
    body = _roster(("Shadowflame", "Liandry's Torment"))

    assert body["breakdown"][SHADOWFLAME_ROW]["total_damage"] > 0.0
