"""Malphite — CP10.4 full-entry-reviewed packet module, plus the E8c P shield
and the P1 W/armor closure.

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

P1 addition over the reviewed packet:
- W (Thunderclap) now prices BOTH sourced parts of the empowered
  attack: the "Additional Physical Damage" on-hit bonus (30-70 + 20% AP
  + 15% armor) and the cone's "Physical Damage" (15-55 + 30% AP + 15%
  armor) as a single-target hit — in a 1v1 the target stands inside the
  melee cone, so both rows land on it (the reviewed packet priced only
  the cone row; the per-auto cone cadence over the 5s window is a
  documented boundary).
- W's passive bonus armor ("Malphite gains bonus armor, tripled while
  Granite Shield is active" — cached W first effect; the "Increased
  Bonus Armor" leveling row 30/45/60/75/90 % armor IS the tripled
  value) is a BUFF-phase grant: it mutates the shared parse stats so
  E's 40% armor ratio and W's own 15% armor ratios price the buffed
  armor.  The module models Granite Shield as active for the whole
  window (the E8c assumption), so the tripled value applies for the
  whole fight; the shield-break revert is part of that documented
  boundary.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import (
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    with_control,
)

PACKET_SHA256 = "486c8deb9501df4c594a7d0e7c89daa625c864c627339407758da466dfc7c1e1"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Malphite", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec

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


def _thunderclap(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: tripled-armor buff, then the empowered-attack parts (on-hit + cone).

    BUFF phase so E (40% armor ratio) parses after the armor grant.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    # W passive: bonus armor, tripled while Granite Shield is active.  The
    # cached "Increased Bonus Armor" row (30/45/60/75/90 % armor) IS the
    # tripled value; the module treats the shield as active for the whole
    # fight window (E8c assumption), so the grant feeds every armor-scaled
    # row in the parse (E's 40% and W's own 15% armor ratios).
    armor_grant = extract_named(
        ability, "Increased Bonus Armor", rank, ctx.stats, ctx.target
    )
    if armor_grant > 0.0:
        ctx.stats["armor"] = ctx.stats.get("armor", 0.0) + armor_grant
        ctx.stats["bonus_armor"] = ctx.stats.get("bonus_armor", 0.0) + armor_grant
    on_hit_bonus = extract_named(
        ability, "Additional Physical Damage", rank, ctx.stats, ctx.target
    )
    cone = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    total = on_hit_bonus + cone
    entry = damage_entry(
        ability.get("name", "Thunderclap"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", on_hit_bonus),
        DamagePart("physical", cone),
    )
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"empowered-attack on-hit {on_hit_bonus:g} (Additional Physical "
        f"Damage) + single-target cone {cone:g} (Physical Damage); W "
        f"passive grants {armor_grant:g} bonus armor (tripled while "
        "Granite Shield is active) feeding E's and W's armor ratios"
    )
    return entry


_thunderclap.phase = BUFF


SLOTS = dict(SLOTS)
_packet_q = SLOTS["Q"]
_packet_r = SLOTS["R"]
SLOTS["Q"] = _seismic_shard
SLOTS["W"] = _thunderclap
SLOTS["R"] = with_control(
    _packet_r,
    kind="airborne",
    duration_attr="Knock Up Duration",
)
parse_abilities = build_parser(SLOTS, "Malphite")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Granite Shield) is modeled as a pre-fight granted shield: 10% of "
    "max HP spanning the fight window, riding the first Q cast. The "
    "until-broken lifetime is approximated as the full window; the "
    "out-of-combat replenishment trigger is a documented boundary",
    "W (Thunderclap) prices both empowered-attack parts: the Additional "
    "Physical Damage on-hit bonus and the cone's Physical Damage as a "
    "single-target hit (the 1v1 target stands inside the melee cone).  "
    "The cone's per-auto cadence over its 5s window is a documented "
    "boundary — the packet prices one cone hit at the cast",
    "W's passive bonus armor is granted at its tripled value (the cached "
    "Increased Bonus Armor row) for the whole fight, matching the E8c "
    "full-window Granite Shield assumption; the shield-break revert to "
    "the un-tripled value is part of that documented boundary",
    "R's sourced 1.5-second knockup counts as target action downtime",
]

MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
