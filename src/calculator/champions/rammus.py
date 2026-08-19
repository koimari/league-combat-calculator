"""Rammus — CP10.6 full-entry-reviewed packet module, plus the E9-3 W fix.

E9-3: Defensive Ball Curl (W) is a defensive stance whose damage is the
THORNS proc against basic-attacking enemies: "enemies that use a basic
attack on-hit against Rammus are dealt 15 (+ 10% total armor) (+ 10%
total magic resistance) magic damage".  The reviewed packet misread the
stance's 'Bonus Armor' leveling row as magic damage (47 + 60% armor
against MR at rank 5); the thorns formula has NO leveling row in the
cache, so it is pinned here as wiki prose with the source cited.  The
module prices the thorns damage per enemy basic attack that lands
during the stance via the ``w_thorns_autos`` option (0 by default — the
fight engine has no incoming-auto hook, so the enemy's auto count is
explicit state); the stance's bonus armor/MR rows are the defensive
buff, not damage, and remain state.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown

# HARDCODED: verify on patch updates — the thorns formula exists only in
# the cached W description prose ("enemies that use a basic attack
# on-hit against Rammus are dealt 15 (+ 10% total armor) (+ 10% total
# magic resistance) magic damage"); there is no leveling row for it.
_THORNS_BASE = 15.0
_THORNS_ARMOR_RATIO = 0.10
_THORNS_MAGIC_RESISTANCE_RATIO = 0.10

PACKET_SHA256 = "e48aa5766d5565b485a6d7fa34421f25d11f56fdcfdec5bb0c0823acc991e0f0"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rammus",
    PACKET_SHA256,
    # Powerball stops on the enemy it collides with and Soaring Slam lands
    # one impact — the boundary claim that carries MODULE_CC's reviewed
    # answers into the event ledger.
    single_hit_slots=frozenset({"Q", "R"}),
)
PACKET_SPEC = SLOTS.packet_spec


def _defensive_ball_curl(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the thorns damage per enemy basic attack during the stance."""
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    autos = min(max(int(ctx.option("w_thorns_autos")), 0), 30)
    armor = float(ctx.stat("armor") or 0.0)
    magic_resistance = float(ctx.stat("magic_resistance") or 0.0)
    per_auto = (
        _THORNS_BASE
        + _THORNS_ARMOR_RATIO * armor
        + _THORNS_MAGIC_RESISTANCE_RATIO * magic_resistance
    )
    total = per_auto * autos
    # The thorns row answers its own crowd control instead of MODULE_CC,
    # because it can only answer when it prices a single reactive hit: the
    # stance retaliates against enemy basic attacks, whose arrival times
    # nothing sources, so a row of several of them is one aggregate with no
    # per-hit boundary for the marker to ride.  The stance applies no
    # control either way, and says so wherever the ledger can hear it.
    count = max(autos, 1)
    certified = count <= 1
    entry = damage_entry(
        "Defensive Ball Curl (thorns)",
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        event_order_certified="single_hit" if certified else None,
    )
    entry["parts"] = (
        DamagePart(
            "magic", per_auto, count=count, cc_kind="none" if certified else None
        ),
    )
    entry["detail"] = (
        f"thorns: {per_auto:.2f} magic damage per enemy basic attack "
        f"(15 + 10% total armor ({armor:.1f}) + 10% total magic "
        f"resistance ({magic_resistance:.1f})) x {autos} auto(s) that hit "
        "Rammus during the stance; the stance's bonus armor/MR rows are "
        "the defensive buff, not damage"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["W"] = _defensive_ball_curl

# Cached kit review.  Q's collision deals magic damage while "knocking them
# back 125 units" and the enemies hit "are then stunned ... as well as
# slowed": two immobilize kinds from one cast, which is what the
# un-narrowed "immobilize" states.  R's impact "deals magic damage to
# nearby enemies and slows them for 1.5 seconds"; the epicentre knock-up is
# gated on Soaring Slam being cast during Powerball, a combination this
# module does not price.  W answers per part (``_defensive_ball_curl``).  E
# taunts, but "monsters are additionally dealt magic damage" is its only
# damage row, so against a champion it emits nothing; P is a stat innate.
MODULE_CC = {"Q": "immobilize", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Rammus", cc_kinds=MODULE_CC)

OPTIONS = list(OPTIONS) + [
    {
        "key": "w_thorns_autos",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 30,
        "label": "Enemy basic attacks during Defensive Ball Curl",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Defensive Ball Curl) prices the thorns damage — 15 + 10% total "
    "armor + 10% total magic resistance magic damage per enemy basic "
    "attack that hits Rammus during the stance (cached W description "
    "prose; there is no leveling row). The fight engine has no "
    "incoming-auto hook, so w_thorns_autos is the explicit count of "
    "enemy autos (0 = none). The reviewed packet's misread of the "
    "'Bonus Armor' row as magic damage is removed; the stance's bonus "
    "armor/MR rows are the defensive buff and remain state.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
