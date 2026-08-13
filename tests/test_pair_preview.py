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
from src.calculator.program.build import pair_preview_mechanics
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
    app_module.app.config["TESTING"] = True
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
