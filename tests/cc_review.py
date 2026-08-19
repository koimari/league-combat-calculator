"""Shared reads for the champion crowd-control reviews (``MODULE_CC``).

Every champion test that declares reviewed crowd control makes the same
two claims, so the reads behind them live here once instead of in each
file:

* the declared kind is the one the **cached** ability text gives — the
  module reviewed a kit, not a memory — which is what
  :func:`slot_text` and :func:`control_words` check; and
* the declaration reaches the event ledger, where the control-armed item
  passives read it, which is what :func:`fimbulwinter_coverage` and
  :func:`unreviewed_ability_slots` check.

This is a test helper, not a test module: it holds no assertions.
"""

from src.calculator.calculate import calculate_payload
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import (
    load_public_champion,
    parse_scenario_request,
    resolve_scenario,
)

# Every control word the Wiki uses for the classes a control-armed item
# passive can key on.  A reviewed "none" slot whose cached text contains
# one of these has either been misread or has changed under the module.
CONTROL_WORDS = (
    "airborne",
    "charm",
    "fear",
    "flee",
    "immobiliz",
    "knock",
    "pull",
    "root",
    "sleep",
    "slow",
    "snare",
    "stasis",
    "stun",
    "suppress",
    "taunt",
)

_PROBE = {
    "level": 18,
    "items": ["Fimbulwinter"],
    "fight_mode": "timed",
    "include_auto_attacks": True,
}


def kit(champion):
    """The champion's cached data, exactly as the module parses it."""
    return load_public_champion(champion)


def slot_text(champion_data, slot):
    """Every cached description of one slot, lowercased and joined.

    Recast slots (``Q2``) have no cached slot of their own — both casts
    live under the parent letter — so callers pass the parent.
    """
    return " ".join(
        (effect.get("description") or "")
        for ability in champion_data["abilities"].get(slot, [])
        for effect in ability.get("effects", []) or []
    ).lower()


def control_words(text):
    """The control vocabulary present in *text*, sorted."""
    return sorted(word for word in CONTROL_WORDS if word in text)


def fimbulwinter_coverage(champion):
    """The campaign's control-token probe, through the public entry."""
    return calculate_payload({"champion": champion, **_PROBE})["timeline_coverage"]


def unreviewed_ability_slots(champion):
    """Ability event sources the ledger shows with no reviewed cc kind.

    This is the coverage refusal's own reason, named: the control-armed
    scan goes coarse exactly when this list is non-empty.
    """
    request = {"champion": champion, **_PROBE}
    resolved = resolve_scenario(parse_scenario_request(request))
    result = run_fight(
        resolved.champion_data,
        _PROBE["level"],
        resolved.items,
        FightParams.from_request(request),
    )
    return sorted(
        {
            event["source_key"]
            for event in result["damage_events"]
            if event.get("is_ability") and not event.get("cc_reviewed")
        }
    )
