"""Malphite — CP10.4 full-entry-reviewed packet module, plus the E8c P shield.

E8c addition over the reviewed packet:
- P (Granite Shield) is a 10%-of-max-HP barrier that "lasts until it is
  broken" (cached passive description).  The passive has no cast, so the
  shield rides the first Q damage event as a ``self_shield_events``
  payload: the shared ledger grants it as a timed self-shield spanning
  the fight window (an until-broken barrier approximated as
  full-window), so incoming damage is absorbed before health.  The
  out-of-combat regeneration ("replenishes to full strength after a few
  seconds of not taking damage") is a documented boundary — the model
  grants the full shield once at fight start.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .reviewed_batch_04 import build_batch_module
from .slotlib import attach_self_shield

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Malphite")

# HARDCODED: verify on patch updates — Granite Shield's 10% ratio and
# until-broken lifetime are prose-only in the cached passive description
# (data/champions.json, Malphite P): "grants himself a shield equal to
# 10% of his maximum health. The shield lasts until it is broken, and
# replenishes to full strength after a few seconds of not taking
# damage."
GRANITE_SHIELD_MAX_HP_RATIO = 0.10  # 10% of maximum health
_DEFAULT_FIGHT_WINDOW_SECONDS = 5.0  # one-rotation fallback


def _seismic_shard(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the reviewed magic hit carrying Granite Shield's pre-fight shield."""
    entry = _packet_q(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = GRANITE_SHIELD_MAX_HP_RATIO * ctx.stats.get("health", 0.0)
    try:
        window = float(ctx.options.get("fight_duration_seconds"))
    except (TypeError, ValueError):
        window = _DEFAULT_FIGHT_WINDOW_SECONDS
    if not window or window <= 0.0:
        window = _DEFAULT_FIGHT_WINDOW_SECONDS
    entry["event_order_certified"] = "single_hit"
    return attach_self_shield(
        entry,
        amount=shield,
        duration=float(window),
        source="Granite Shield",
        detail=(
            f"Q carries Granite Shield's pre-fight barrier: {shield:g} "
            f"({GRANITE_SHIELD_MAX_HP_RATIO * 100:g}% of max HP), until "
            f"broken (modeled as the {window:g}s fight window)"
        ),
    )


SLOTS = dict(SLOTS)
_packet_q = SLOTS["Q"]
SLOTS["Q"] = _seismic_shard
parse_abilities = build_parser(SLOTS, "Malphite")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Granite Shield) is modeled as a pre-fight granted shield: 10% of "
    "max HP spanning the fight window, riding the first Q cast. The "
    "until-broken lifetime is approximated as the full window; the "
    "out-of-combat replenishment trigger is a documented boundary",
]

MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
