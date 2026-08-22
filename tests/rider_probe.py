"""Shared reads for the damage riders that ride basic attacks.

A rider (Warwick's Eternal Hunger, Miss Fortune's Love Tap, Shaco's
Backstab, Sylas' Petricite Burst, Xin Zhao's Determination) is priced in
two places and its test makes the same two claims about both:

* the module's parsed entry carries the per-hit number the wiki sentence
  gives — :func:`tests.row_review.entry` reads that at one fixed stat
  block; and
* that number reaches the fight's total through the public entry, as the
  ``on_hit_ability_passive`` breakdown row — which is what :func:`fight`
  and :func:`rider_row` read.

The fight goes through ``calculate_payload``, the same call ``/api/
calculate`` makes, so a rider that parses but never lands is caught here
rather than in a parser assertion that cannot see the fight.

This is a test helper, not a test module: it holds no assertions.
"""

from src.calculator.calculate import calculate_payload

RIDER_ROW = "on_hit_ability_passive"

_PROBE = {
    "level": 18,
    "items": [],
    "fight_mode": "timed",
    "include_auto_attacks": True,
}


def fight(champion, *, deterministic=False, **request):
    """One timed, autos-on fight through the public calculate entry.

    ``request`` overrides the probe (``champion_options``, ``items``,
    ``level``) exactly as a caller would.  ``deterministic`` is the crit
    roll's seed switch, required on any crit-capable build.
    """
    return calculate_payload(
        {"champion": champion, **_PROBE, **request}, deterministic=deterministic
    )


def rider_row(champion, **request):
    """The passive rider's breakdown row from that fight."""
    return fight(champion, **request)["breakdown"][RIDER_ROW]


def healing_from(result, source):
    """Total self-healing one named source paid in a fight result."""
    return sum(
        float(event.get("amount", 0.0))
        for event in result.get("self_healing_events") or []
        if event.get("source") == source
    )
