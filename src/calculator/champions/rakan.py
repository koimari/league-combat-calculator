"""Rakan — revision-backed offensive slot map.

Gleaming Quill and Grand Entrance each deal one magic-damage instance. The
Quickness damages each enemy at most once per cast, so every selected enemy
receives one hit. Fey Feathers and Battle Dance do not damage enemies.

E8d ally-support: Q (Gleaming Quill) heals Rakan and nearby allies (cached
Heal 40-230 by level + 55% AP; scope self_and_all_teammates) — the event is
authored by the engine's ally-support scanner from cached leveling at the Q
cast time.  P (Fancy Footwork) is a passive periodic self-shield (cached
Shield 30-247.94 by level + 95% AP); the scanner only reads Q/W/E/R slots,
so the passive shield is a documented missing engine hook, not an emitted
packet.
"""

from typing import Any

from .engine import build_parser
from .slotlib import attach_self_shield, simple_damage

OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Gleaming Quill counts one enemy hit; its ally heal is excluded.",
    "Grand Entrance counts one completed landing hit.",
    "The Quickness counts one collision per selected enemy; one cast cannot "
    "damage an enemy twice.",
    "Battle Dance is excluded because it deals no enemy damage.",
    "Fey Feathers' periodic self-shield (30:247.94 by level + 95% AP) rides "
    "the first damaging cast (Q) as a timed shield for the fight window; "
    "the periodic/out-of-combat refresh cadence is state.",
]

SOURCES = [
    {
        "label": "Fey Feathers",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Fey_Feathers",
        "revision_id": 4016025,
        "revision_timestamp": "2026-05-08T17:35:55Z",
    },
    {
        "label": "Gleaming Quill",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Gleaming_Quill",
        "revision_id": 3996425,
        "revision_timestamp": "2026-03-04T16:52:28Z",
    },
    {
        "label": "Grand Entrance",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Grand_Entrance",
        "revision_id": 4007760,
        "revision_timestamp": "2026-04-12T14:15:53Z",
    },
    {
        "label": "Battle Dance",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Battle_Dance",
        "revision_id": 4008001,
        "revision_timestamp": "2026-04-13T02:59:27Z",
    },
    {
        "label": "The Quickness",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/The_Quickness",
        "revision_id": 3971183,
        "revision_timestamp": "2025-12-02T06:20:48Z",
    },
]

# HARDCODED: verify on patch updates — Fey Feathers' shield is the cached
# "Shield" per-level row (30 : 247.94 based on level) + 95% AP; the
# "until broken" shield is modeled as the fight window (E8c passive-shield
# convention).  The shield rides the first damaging cast (Q) so the shared
# ledger can grant it as a timed self-shield.
_P_SHIELD_BASE_LEVEL_1 = 30.0
_P_SHIELD_BASE_LEVEL_18 = 247.94
_P_SHIELD_AP_RATIO = 0.95
_P_SHIELD_DURATION_SECONDS = 10.0


def _p_shield_amount(level: int, ability_power: float) -> float:
    base = _P_SHIELD_BASE_LEVEL_1 + (
        _P_SHIELD_BASE_LEVEL_18 - _P_SHIELD_BASE_LEVEL_1
    ) * ((level - 1) / 17.0)
    return base + _P_SHIELD_AP_RATIO * ability_power


def _q_with_p_shield(ctx: Any) -> dict[str, Any] | None:
    entry = simple_damage(attr="Magic Damage", dmg_type="magic")(ctx)
    if entry is None or int(entry.get("rank", 0) or 0) < 1:
        return entry
    shield = _p_shield_amount(ctx.level, ctx.stat("ability_power"))
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_P_SHIELD_DURATION_SECONDS,
        source="Fey Feathers",
        detail=(
            f"Q cast also grants the periodic Fey Feathers self-shield "
            f"({shield:g} for {_P_SHIELD_DURATION_SECONDS:g}s, 30:247.94 "
            f"by level + 95% AP; until-broken modeled as the window)"
        ),
    )


SLOTS = {
    "Q": _q_with_p_shield,
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Rakan")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Rakan")
