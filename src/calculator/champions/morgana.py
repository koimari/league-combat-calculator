"""Morgana — CP10.4 packet module with the E9-1 gap fixes.

E9-1 closes the three remaining audit gaps over the CP10.4 packet:
- W (Tormented Shadow) prices all 10 storm ticks: "Maximum Damage Per
  Tick" x 10 == "Maximum Total Damage" at every rank (the packet
  priced ONE tick).  The storm lasts 5 seconds, dealing magic damage
  "on-cast and every 0.5 seconds thereafter".
- R (Soul Shackles) prices the initial hit AND the same magic damage
  again when the 3-second tether breaks: "Total Magic Damage" == 2 x
  "Magic Damage" at every rank (the packet priced only the initial
  hit).
- P (Soul Siphon) heals Morgana for 18% of the post-mitigation damage
  dealt by her abilities (authored by the HEALING_RULE_CHAMPIONS rule
  in healing.py); the passive slot itself stays a zero-damage row.

Q (Dark Binding) packet is a correct single-instance read; E (Black
Shield) is a documented no-damage shield.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

# Sourced storm cadence (wiki W): "take magic damage on-cast and every
# 0.5 seconds thereafter" over the 5-second desecrated area -> 10 ticks
# of "Maximum Damage Per Tick" == "Maximum Total Damage".
_W_TICKS = 10
_W_TICK_INTERVAL = 0.5
_W_DURATION = 5.0
# R tether length (wiki R): the second hit lands when the 3-second
# tether breaks ("If a target does not break their tether by the end of
# its duration, they are dealt the same magic damage again").
_R_TETHER_SECONDS = 3.0


def _tormented_shadow(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: 10 ticks of Maximum Damage Per Tick == Maximum Total Damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_tick = extract_named(
        ability, "Maximum Damage Per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Tormented Shadow"),
        rank,
        extract_cooldown(ability, rank),
        per_tick * _W_TICKS,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_W_TICKS,
            time_offset=0.0,
            hit_interval=_W_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _W_DURATION
    entry["detail"] = (
        f"{_W_TICKS} sourced {_W_TICK_INTERVAL:g}s-interval ticks "
        f"(Maximum Damage Per Tick x{_W_TICKS} == Maximum Total Damage)"
    )
    return entry


def _soul_shackles(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: initial hit + the same damage again at the 3s tether break."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Soul Shackles"),
        rank,
        extract_cooldown(ability, rank),
        initial * 2,
        "magic",
    )
    # The two hits apply two different controls — the shackling slows by
    # 20% for the tether, and only the unbroken tether "become[s] stunned
    # for a duration" — so R's kinds are per part rather than per slot
    # and are authored here instead of in MODULE_CC.
    entry["parts"] = (
        DamagePart("magic", initial, time_offset=0.0, cc_kind="slow"),
        DamagePart("magic", initial, time_offset=_R_TETHER_SECONDS, cc_kind="stun"),
    )
    entry["dot_duration"] = _R_TETHER_SECONDS
    entry["detail"] = (
        f"initial hit + the same {initial:.6g} magic damage at the "
        f"{_R_TETHER_SECONDS:g}s tether break (Magic Damage x2 == "
        "Total Magic Damage)"
    )
    return entry


def _soul_siphon(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: self-heal passive — no enemy damage (healing.py authors it)."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Soul Siphon"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Soul Siphon heals Morgana for 18% of the post-mitigation "
            "damage dealt by her abilities (authored by the "
            "HEALING_RULE_CHAMPIONS rule in healing.py); the passive "
            "itself deals no enemy damage."
        ),
    }


PACKET_SHA256 = "5cc8fcb312de2d1d31c8b63157dac32a85424fa0decca7a8f1ac4ac94d689a9d"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Morgana",
    PACKET_SHA256,
    # Dark Binding's sphere deals its packet once, to the first enemy it
    # hits, at the cast — the boundary claim that carries MODULE_CC's
    # reviewed answer for Q into the event ledger.
    single_hit_slots=frozenset({"Q"}),
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["W"] = _tormented_shadow
SLOTS["R"] = _soul_shackles
SLOTS["P"] = _soul_siphon

# Cached kit review: Q's sphere damages the first enemy hit "and root[s]
# them for a duration"; W's desecrated soil only damages.  R applies two
# controls, one per part, and declares them on its parts
# (``_soul_shackles``).  E shields an ally and P heals Morgana.
MODULE_CC = {"Q": "root", "W": "none"}

parse_abilities = build_parser(SLOTS, "Morgana", cc_kinds=MODULE_CC)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Tormented Shadow) prices all 10 storm ticks (Maximum Damage Per "
    "Tick x10 == Maximum Total Damage 180-700 + 200% AP) at 0.5-second "
    "intervals over the 5-second desecrated area, first tick on-cast.",
    "R (Soul Shackles) prices the initial hit plus the same magic damage "
    "again at the 3-second tether break (Magic Damage x2 == Total Magic "
    "Damage 400-700 + 160% AP); the slow/root and reveal are "
    "crowd-control utility not priced as damage.",
    "P (Soul Siphon) heals Morgana for 18% of the post-mitigation "
    "damage dealt by her abilities against champions (healing.py "
    "HEALING_RULE_CHAMPIONS); the passive deals no enemy damage "
    "itself.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Morgana")
