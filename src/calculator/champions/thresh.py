"""Thresh — reviewed packet slots plus the E3 soul-stack passive.

E3 addition over the CP10.8 packet module:
- P (Damnation) becomes a BUFF-phase stack slot: each Soul grants 1
  ability power and 1 bonus armor. The stack count is a user option
  (``souls``, default 40 — the expected mid-game state); the model
  cannot simulate lantern-passive soul farming, so the pre-stacked
  count is priced (module convention for permanent scaling). The AP
  feeds Q/W/E/R scaling because P runs first in the BUFF phase; the
  armor is published as a stat buff for the fight's defensive side.

Coverage: W (Dark Passage) deals no enemy damage — the pinned reviewed
packet declares it ``kind: "no_damage"`` and this module does not
reassign the slot, so W emits that sourced zero row. The ally-support
Dark Passage shield priced through the ally scanner (ASSUMPTIONS below)
is a separate, already-modeled mechanism.
"""

from typing import Any

from .engine import BUFF, SlotCtx
from .slotlib import ability_name
from .packet_module import build_packet_module
from .inputs import int_option
from ..binary_roots import data_value, spell_object

PACKET_SHA256 = "73d6faf368aec7c57d302a065771b4a343b530aeb9da36b99913f298ad06c1be"


# Rooted in ThreshPassiveSouls.StatValuePerSoul; the cached P prose
# corroborates one AP and one bonus armor per soul.
_THRESH_PASSIVE_SOULS = spell_object("Thresh", "ThreshPassiveSouls")
_AP_PER_SOUL = data_value(_THRESH_PASSIVE_SOULS, "StatValuePerSoul")
_ARMOR_PER_SOUL = data_value(_THRESH_PASSIVE_SOULS, "StatValuePerSoul")
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
    ctx.stats["ability_power"] = ctx.stat("ability_power") + bonus_ap

    return {
        "name": ability_name(ability),
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


# Reviewed crowd control, read from the cached kit.  Q (Death Sentence)'s
# scythe catches to "deal magic damage, stun and reveal them for 1.5
# seconds, and render them airborne for 0.4 seconds" — two immobilize
# kinds on one target, so the reviewed answer is the un-narrowed one.  E
# (Flay): enemies "are dealt magic damage and knocked 200 units in the
# target direction, and then are slowed for 1 second" — the knock-back is
# the immobilizing half.  R (The Box): a wall breaks "dealing magic damage
# and slowing them by 99% for 2 seconds".  P is a soul-stack buff and W is
# a lantern shield, neither of which damages.
MODULE_CC = {"Q": "immobilize", "E": "knockback", "R": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Thresh",
    PACKET_SHA256,
    # Each packet is one blow: the scythe "catches the first enemy
    # hit", Flay "sweeps his chain" once, and one Box wall breaks on
    # contact — so each row is a hit the ledger can time.
    single_hit_slots=frozenset({"Q", "E", "R"}),
    slot_parsers={
        "P": _damnation,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    int_option(
        "souls", _DEFAULT_SOULS, minimum=0, maximum=_MAX_SOULS, label="Souls collected"
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
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
    "W (Dark Passage) has no enemy-damage formula: the lantern dash and "
    "its shield are self/ally utility only (confirmed by the pinned "
    "reviewed packet's kind='no_damage' declaration for W). W is a cast "
    "slot in this module: it emits the packet's sourced zero-damage row "
    "while the support scanner prices the lantern shield, so the slot is "
    "modeled.",
]
