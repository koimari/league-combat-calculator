"""E9-BIS-A: event-order certification for the last 5 BIS champions.

Smolder, Talon, Twitch, Vel'Koz and Viego all emitted champion rows
without authored event order (or with cast_boundary-only precision), so
every one of their 96 BIS candidates evaluated as 'partial' and the
optimizer certified none ("No candidate has complete sourced event
order").  This is the same failure Varus had before 938bf9a.

The module fixes follow the Varus pattern:

- one-instance ability slots carry ``event_order_certified =
  "single_hit"`` so damage.py authors an exact per-cast hit event;
- proc rows (Talon P Blade's End, Twitch P Deadly Venom, Vel'Koz P
  Organic Deconstruction) declare a sourced ``damage_events`` ledger
  (one event per proc instance) that damage.py re-prices at the proc's
  mitigated total;
- multi-part strikes (Twitch E Contaminate, Viego R Heartbreaker) and
  the Smolder Q tier-3 burn post-hit proc carry ``DamagePart(
  time_offset=0.0)`` so the coverage classifier sees authored
  "hit"-precision timing instead of a coarse cast boundary.

Every fix is timing metadata: no champion-authored damage formula or
constant changes, so the golden baseline's champion and item totals stay
identical.  The one exception is the Twitch 11 sustained magic_build
fight: the poison proc's authored window-end position now lands after the
tail autos, so Cinderbloom's below-40% bonus applies where the old coarse
fallback (last cast time) had not yet crossed the threshold — the same
window-order interaction Varus's certification fix introduced.

Each test drives /api/calculate fights (level 18, basic abilities rank 5,
ultimate rank 3, no items, 0 resists) in one_rotation and time_based
modes and asserts ``timeline_coverage`` is complete with no coarse
sources, then drives /api/bis (mid and bottom roles) and asserts
``certified_candidate_count > 0`` — the empirical gate the optimizer
actually uses.
"""

import pytest

from src import app as app_module

CHAMPIONS = ["Smolder", "Talon", "Twitch", "Vel'Koz", "Viego"]

# The source that was coarse (uncertified) before this fix, per champion.
PREVIOUSLY_COARSE = {
    "Smolder": {"Q", "dragon_practice_burn"},
    "Talon": {"passive"},
    "Twitch": {"passive"},
    "Vel'Koz": {"passive"},
    "Viego": {"R"},
}

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _calculate(
    champion: str,
    *,
    one_rotation: bool = False,
    include_auto_attacks: bool = False,
) -> dict:
    """One /api/calculate fight; level 18, no items, 0 target resists."""
    payload: dict = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "fight_mode": "one_rotation" if one_rotation else "time_based",
        "fight_duration": 10.0,
        "include_auto_attacks": include_auto_attacks,
        "auto_attack_uptime": 0.3 if include_auto_attacks else 0.0,
        "ability_ranks": _RANKS,
        "champion_options": {},
        "target_health": 2000.0,
        "target_armor": 0.0,
        "target_mr": 0.0,
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _bis(champion: str, *, role: str) -> dict:
    """One focused /api/bis request with a roster target (mid/bottom, 18)."""
    payload: dict = {
        "champion": champion,
        "level": 18,
        "items": [],
        "boots": "",
        "role": role,
        "ability_ranks": _RANKS,
        "champion_options": {},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": _RANKS,
            }
        ],
    }
    response = app_module.app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


@pytest.mark.parametrize("champion", CHAMPIONS)
@pytest.mark.parametrize("one_rotation", (False, True))
def test_calculate_timeline_coverage_is_complete(champion, one_rotation):
    """One-rotation and time-based fights both certify every damaging row."""
    data = _calculate(champion, one_rotation=one_rotation)
    coverage = data["timeline_coverage"]
    assert coverage["complete"] is True, coverage
    assert coverage["certification"] == "event_order_certified", coverage
    assert coverage["coarse_sources"] == [], coverage
    # The exact source that previously kept every build partial must now
    # carry authored event order.
    assert PREVIOUSLY_COARSE[champion].issubset(
        set(coverage["exact_sources"])
    ), coverage


@pytest.mark.parametrize("champion", CHAMPIONS)
def test_calculate_certifies_with_the_auto_ledger_enabled(champion):
    """The BIS fight window runs autos; coverage must hold there too."""
    data = _calculate(champion, one_rotation=False, include_auto_attacks=True)
    coverage = data["timeline_coverage"]
    assert coverage["complete"] is True, coverage
    assert coverage["coarse_sources"] == [], coverage


@pytest.mark.parametrize("champion", CHAMPIONS)
@pytest.mark.parametrize("role", ("mid", "bottom"))
def test_bis_certifies_candidates(champion, role):
    """BIS must certify a positive candidate count (was 0 for all five)."""
    body = _bis(champion, role=role)
    assert body["candidate_count"] > 0
    assert body["certified_candidate_count"] > 0
    assert body["withheld_candidate_count"] < body["candidate_count"]
    assert body["candidates"], body.get("coverage")
    top = body["candidates"][0]
    assert top["timeline_coverage"]["complete"] is True
