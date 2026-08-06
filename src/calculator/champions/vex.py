"""Vex — CP10.9 full-entry-reviewed packet module, plus the E8c W shield.

E8c addition over the reviewed packet:
- W (Personal Space) deals its magic damage AND shields Vex herself for
  2.5 seconds.  The shield rides the W damage event as a
  ``self_shield_events`` payload (the Eclipse item shape): the shared
  ledger grants a timed self-shield at the event timestamp, so the W
  cast both deals damage and absorbs the sourced amount.  The generic
  ally-support scanner is told to defer this slot (see
  ``support_effects._MODULE_AUTHORED_SHIELD_SLOTS``) — its description
  marker misses "granting herself" and would mis-target the self-only
  shield at a teammate.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .reviewed_batch_09 import build_batch_module
from .slotlib import attach_self_shield, extract_named

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Vex")

# HARDCODED: verify on patch updates — Personal Space's shield duration is
# prose in the cached ability description ("granting herself a shield for
# 2.5 seconds"); the leveling row (data/champions.json, W "Shield
# Strength": 50/75/100/125/150 + 75% AP) is read live below.
_PERSONAL_SPACE_SHIELD_DURATION_SECONDS = 2.5


def _personal_space(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the reviewed magic hit plus the sourced self-shield payload."""
    entry = _packet_w(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = extract_named(
        ctx.ability(), "Shield Strength", rank, ctx.stats, ctx.target
    )
    entry["event_order_certified"] = "single_hit"
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_PERSONAL_SPACE_SHIELD_DURATION_SECONDS,
        source=entry.get("name", "Personal Space"),
        detail=(
            f"W also shields Vex for {shield:g} for "
            f"{_PERSONAL_SPACE_SHIELD_DURATION_SECONDS:g}s (self)"
        ),
    )


SLOTS = dict(SLOTS)
_packet_w = SLOTS["W"]
SLOTS["W"] = _personal_space
parse_abilities = build_parser(SLOTS, "Vex")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Personal Space) grants Vex the sourced shield (flat + 75% AP) for "
    "2.5s at the cast; the shield absorbs damage before health in the "
    "participant ledger.",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
