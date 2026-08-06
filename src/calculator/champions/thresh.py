"""Thresh — reviewed packet slots plus the E3 soul-stack passive.

E3 addition over the CP10.8 packet module:
- P (Damnation) becomes a BUFF-phase stack slot: each Soul grants 1
  ability power and 1 bonus armor. The stack count is a user option
  (``souls``, default 40 — the expected mid-game state); the model
  cannot simulate lantern-passive soul farming, so the pre-stacked
  count is priced (module convention for permanent scaling). The AP
  feeds Q/W/E/R scaling because P runs first in the BUFF phase; the
  armor is published as a stat buff for the fight's defensive side.
"""

from typing import Any

from .engine import BUFF, SlotCtx, build_parser
from .reviewed_batch_08 import build_batch_module

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_batch_module("Thresh")
)

# HARDCODED: verify on patch updates — Damnation's per-soul values
# (1 AP, 1 bonus armor) are wiki prose; the JSON carries no leveling
# for the passive at all.
_AP_PER_SOUL = 1.0
_ARMOR_PER_SOUL = 1.0
_DEFAULT_SOULS = 40
_MAX_SOULS = 500


def _damnation(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: +1 AP and +1 bonus armor per Soul stack (BUFF phase)."""
    ability = ctx.ability()
    if ability is None:
        return None

    souls = int(ctx.options.get("souls", _DEFAULT_SOULS))
    souls = min(max(souls, 0), _MAX_SOULS)
    bonus_ap = _AP_PER_SOUL * souls
    bonus_armor = _ARMOR_PER_SOUL * souls

    # BUFF phase guarantee: Q/W/E/R parse against the soul-buffed AP.
    ctx.stats["ability_power"] = ctx.stats.get("ability_power", 0.0) + bonus_ap

    return {
        "name": ability.get("name", "Damnation"),
        "rank": ctx.level,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "stat_buff": {
            "ability_power": bonus_ap,
            "bonus_armor": bonus_armor,
        },
        "detail": (
            f"{souls} Soul stack(s): +{bonus_ap:g} ability power, "
            f"+{bonus_armor:g} bonus armor"
        ),
    }


_damnation.phase = BUFF


SLOTS = {**_packet_slots, "P": _damnation}
parse_abilities = build_parser(SLOTS, "Thresh")

OPTIONS = list(_packet_options) + [
    {
        "key": "souls",
        "type": "int",
        "default": _DEFAULT_SOULS,
        "min": 0,
        "max": _MAX_SOULS,
        "label": "Souls collected",
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
    "Soul count is user-set (default 40 — the expected mid-game state); "
    "soul farming is not simulated",
    "Each Soul grants 1 ability power and 1 bonus armor — wiki prose "
    "(module constants); the AP buff applies before all damage slots "
    "parse",
    "W (Dark Passage) and all CC are utility only — no damage",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
