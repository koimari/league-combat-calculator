"""Shaco — CP10.7 full-entry-reviewed packet module.

E4 summon: W (Jack in the Box) is a summoned trap.  Once sprung, the box
remains for 5 seconds and "automatically fire[s] at nearby visible
enemies every 0.5 seconds" — up to 10 attacks at the sourced cadence.
Against a single target (the fight model's duel) the box always attacks
only one enemy, so each shot uses its "Increased Damage" row
(25/40/55/70/85 + 18% AP by rank) rather than the plain Magic Damage
row.  One fully-sprung box prices ``w_box_attacks`` x Increased Damage.

- ``w_box_attacks`` (default 10) — the player-controlled uptime: 10 is
  the box's full sprung lifetime at the sourced 0.5s cadence; reduce it
  to model the target leaving the box's 450 range mid-fight.
- The fear/root/slow are crowd-control utility the fight model does not
  price (the root and fear hold the target in place — that is exactly
  the assumption behind the full-volley default).

Boundary: box HP/stealth, arm time, trigger radius, targeting AI and
leash range are state outside the damage model.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_07 import build_batch_module
from .slotlib import damage_entry, extract_cooldown, extract_named

# Sourced box attack pattern (wiki Shaco W + "Champion summoned units"
# page): the sprung box fires every 0.5 seconds for its 5-second
# lifetime == 10 attacks max.
_BOX_ATTACK_INTERVAL = 0.5
_BOX_SPRUNG_SECONDS = 5.0
_BOX_MAX_ATTACKS = int(_BOX_SPRUNG_SECONDS / _BOX_ATTACK_INTERVAL)  # 10


def _jack_in_the_box(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the sprung box's single-target attack volley."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attacks = min(
        max(int(ctx.options.get("w_box_attacks", _BOX_MAX_ATTACKS)), 1),
        _BOX_MAX_ATTACKS,
    )
    per_shot = extract_named(ability, "Increased Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Jack in the Box"),
        rank,
        extract_cooldown(ability, rank),
        per_shot * attacks,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_shot,
            count=attacks,
            time_offset=0.0,
            hit_interval=_BOX_ATTACK_INTERVAL,
        ),
    )
    entry["event_order_certified"] = "sourced box attack cadence"
    entry["detail"] = (
        f"Box fires {attacks} shot(s) at {_BOX_ATTACK_INTERVAL:g}s intervals "
        f"(full {_BOX_SPRUNG_SECONDS:g}s sprung lifetime), each using the "
        "single-target Increased Damage row; fear/root/slow are utility."
    )
    return entry


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Shaco")
SLOTS["W"] = _jack_in_the_box
parse_abilities = build_parser(SLOTS, "Shaco")
ASSUMPTIONS.extend(
    [
        "W (Jack in the Box) is a summoned trap: the sprung box fires "
        "every 0.5s for its 5-second lifetime (10 shots max); "
        "w_box_attacks is the player-controlled uptime and defaults to "
        "the full sourced volley.",
        "The fight model is a single-target duel, so the box always uses "
        "its Increased Damage row (attacks only one target), never the "
        "plain Magic Damage row.",
        "The fear/root/slow are crowd-control utility the fight model "
        "does not price; box HP, arm time, trigger radius and leash "
        "range are state outside the damage model.",
    ]
)
OPTIONS.append(
    {
        "key": "w_box_attacks",
        "type": "int",
        "default": _BOX_MAX_ATTACKS,
        "min": 1,
        "max": _BOX_MAX_ATTACKS,
        "label": "Jack in the Box attacks",
    }
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
