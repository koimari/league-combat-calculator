"""Rakan — revision-backed offensive slot map.

Gleaming Quill and Grand Entrance each deal one magic-damage instance. The
Quickness damages each enemy at most once per cast, so every selected enemy
receives one hit. Fey Feathers and Battle Dance do not damage enemies.
"""

from typing import Any

from .engine import build_parser
from .slotlib import simple_damage

OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Gleaming Quill counts one enemy hit; its ally heal is excluded.",
    "Grand Entrance counts one completed landing hit.",
    "The Quickness counts one collision per selected enemy; one cast cannot "
    "damage an enemy twice.",
    "Fey Feathers and Battle Dance are excluded because they deal no enemy damage.",
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

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Rakan")
