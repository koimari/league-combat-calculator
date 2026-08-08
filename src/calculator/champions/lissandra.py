"""Lissandra — revision-backed direct-damage slot map.

Q, W, E, and R each deal one sourced magic-damage instance. E's recast only
moves Lissandra, while R's ice field deals the same damage whether she targets
herself or an enemy. Iceborn Subjugation is excluded because it requires a
champion death; the selected fight does not invent one.
"""

from typing import Any

from .engine import build_parser
from .slotlib import simple_damage

OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Iceborn Subjugation is excluded because no champion death is assumed.",
    "Glacial Path counts its outward hit; the recast is movement only.",
    "Frozen Tomb counts one ice-field hit, whether cast on Lissandra or an enemy.",
]

SOURCES = [
    {
        "label": "Ice Shard",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Ice_Shard",
        "revision_id": 4007664,
        "revision_timestamp": "2026-04-12T10:26:56Z",
    },
    {
        "label": "Ring of Frost",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Ring_of_Frost",
        "revision_id": 3936419,
        "revision_timestamp": "2025-07-24T17:33:52Z",
    },
    {
        "label": "Glacial Path",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Glacial_Path",
        "revision_id": 4007666,
        "revision_timestamp": "2026-04-12T10:34:41Z",
    },
    {
        "label": "Frozen Tomb",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Frozen_Tomb",
        "revision_id": 4017996,
        "revision_timestamp": "2026-05-14T13:55:57Z",
    },
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Lissandra")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Lissandra")
