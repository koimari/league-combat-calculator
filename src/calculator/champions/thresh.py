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
from .packet_module import build_packet_module

PACKET_SHA256 = "73d6faf368aec7c57d302a065771b4a343b530aeb9da36b99913f298ad06c1be"

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_packet_module("Thresh", PACKET_SHA256)
)
PACKET_SPEC = _packet_slots.packet_spec

# HARDCODED: verify on patch updates — Damnation's per-soul values
# (1 AP, 1 bonus armor) are wiki prose; the JSON carries no leveling
# for the passive at all.
_AP_PER_SOUL = 1.0
_ARMOR_PER_SOUL = 1.0
_DEFAULT_SOULS = 40
_MAX_SOULS = 500
# HARDCODED: verify on patch updates — Dark Passage's shield is an ALLY
# shield: cached description ("Thresh and the first allied champion to
# come near the lantern are granted a shield for 4 seconds") and the
# Shield Strength row (50/70/90/110/130 + 2 per Soul collected).  The
# ally-support scanner emits the packet to the selected teammate (its
# description markers do not include Thresh himself as a recipient, so
# in a 1v1 with no ally the packet is dropped — documented boundary);
# the 2-per-Soul term is unpriced by the scanner, which reads the flat
# component only.
_DARK_PASSAGE_SHIELD_DURATION_SECONDS = 4.0
_DARK_PASSAGE_SHIELD_PER_SOUL = 2.0


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
    "W (Dark Passage) shields Thresh and the first allied champion for "
    "4s at the cast; the ally-support scanner emits the ally packet "
    "(flat 50/70/90/110/130; the +2-per-Soul term and Thresh's own "
    "portion are documented boundaries), which absorbs incoming damage "
    "in the participant ledger when a teammate is selected",
    "All other CC is utility only — no damage",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
