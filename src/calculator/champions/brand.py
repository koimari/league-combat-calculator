"""Brand — slot map for the archetype engine.

Why each slot is non-generic:
- P (Blaze) is invisible to the generic parser and needs two custom
  pieces. The Ablaze DoT (2% of target max HP per stack over 4 s) is
  prose-only — P effect[1] has no leveling entry — so it lives as a
  hardcoded constant below. The 3-stack detonation reads the 40-entry
  per-level "Max Health Damage" array (effect[2]) plus 2% per 100 AP.
  Both depend on how many stacks the rotation applies (Q/W/E = 1 each,
  R = 1 per bounce), so P lists AFTER the damage slots and counts them
  from ``ctx.results``. P effect[0]'s "Per-Level Scaling" [20..40] is
  the mana refund on takedown and must contribute zero damage.
- W (Pillar of Flame) is always Ablaze-empowered: the "Increased
  Damage" attribute (effect[1]), not the base "Magic Damage" the
  classifier would pick.
- R (Pyroclasm) is per-bounce "Magic Damage" x the ``r_bounces``
  option. The same leveling also carries "Total Single-Target Damage"
  (3-bounce total) — summing both double-counts, so the per-bounce
  read is pinned in a custom fn.
- Q/E are plain "Magic Damage" reads, pinned explicitly.
- Q's stun, E's spread doubling, and R's slow are utility-only.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    pct_health_per_hit,
    simple_damage,
    with_control,
)

# HARDCODED: verify on patch updates — the Ablaze DoT is prose-only in
# the JSON (P effect[1] has no leveling entry): each stack deals 2% of
# the target's maximum health as magic damage over 4 seconds.
# https://wiki.leagueoflegends.com/en-us/Brand
_ABLAZE_DOT_PCT_MAX_HP = 0.02  # per stack, full 4 s burn

_ABLAZE_DURATION_S = 4.0  # every tick is ability damage: refreshes item burns
_ABLAZE_MAX_STACKS = 3
_R_MAX_BOUNCES = 3


def _r_bounces(options: dict[str, Any]) -> int:
    """Pyroclasm bounces hitting the target, clamped to the in-game 1-3."""
    return max(1, min(_R_MAX_BOUNCES, int(options.get("r_bounces", 3))))


def _pyroclasm(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: per-bounce damage x the r_bounces option (never the JSON total)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    per_bounce = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    total = per_bounce * _r_bounces(ctx.options)
    entry = damage_entry(
        ability.get("name", "Pyroclasm"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    # Pyroclasm has a sourced 0.15-second delay between bounces. Keeping
    # those hits separate lets Blaze stack applications and the ring
    # detonation follow the same event clock.
    entry["parts"] = (
        DamagePart(
            "magic",
            per_bounce,
            count=_r_bounces(ctx.options),
            time_offset=0.0,
            hit_interval=0.15,
        ),
    )
    return entry


def _blaze(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: one rotation's Ablaze DoT + 3-stack detonation, as a proc entry.

    Counts stack applications from the slots that emitted this parse
    (listed after Q/W/E/R in the map): Q/W/E apply 1 each, R applies 1
    per bounce. Stacks cap at 3 and each burns its full 4 s duration;
    the detonation fires only when 3 stacks are reached, once per
    rotation (``proc_count`` schedules the entry outside the cast
    rotation, once per fight).
    """
    ability = ctx.ability()
    if ability is None:
        return None

    applications = sum(1 for slot in ("Q", "W", "E") if slot in ctx.results)
    if "R" in ctx.results:
        applications += _r_bounces(ctx.options)
    if applications < 1:
        return None

    max_hp = ctx.target.get("target_max_health", 0.0)
    stacks = min(applications, _ABLAZE_MAX_STACKS)
    dot_per_stack = _ABLAZE_DOT_PCT_MAX_HP * max_hp
    parts = [DamagePart("magic", dot_per_stack, count=stacks)]

    if applications >= _ABLAZE_MAX_STACKS:
        # Level-indexed % of max HP (40-entry array; linear past 18)
        # plus 2% per 100 AP — modifiers 0 and 1 of "Max Health Damage".
        detonation = pct_health_per_hit(
            ability,
            "Max Health Damage",
            ctx.level,
            ctx.target,
            ap=ctx.stats.get("ability_power", 0.0),
            ap_ratio_per_100=True,
        )
        if detonation is None:
            # None means the attribute vanished (patch rename) — a silent
            # zero would hide Brand's biggest passive hit.
            raise ValueError(
                "Brand P: 'Max Health Damage' is missing from the ability "
                "JSON — cannot compute the Blaze detonation"
            )
        if detonation > 0:
            parts.append(DamagePart("magic", detonation))

    total = sum(part.amount * part.count for part in parts)
    return {
        "name": ability.get("name", "Blaze"),
        "damage_type": "magic",
        "total_raw": total,
        "parts": tuple(parts),
        "proc_count": 1,
        # Ablaze ticks are ability damage for 4 s past the last cast,
        # so item burns (Liandry's, Blackfire) stay refreshed that long.
        "dot_duration": _ABLAZE_DURATION_S,
        "dot_tick_interval": 0.25,
        "timeline_event_model": "brand_blaze",
        "dot_stack_count": stacks,
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "r_bounces",
        "type": "int",
        "default": 3,
        "label": "R bounces hitting the target",
        "min": 1,
        "max": 3,
    },
]

ASSUMPTIONS = [
    "Every Ablaze stack burns its full 4-second duration (2% of target "
    "max HP per stack, max 3 stacks per rotation)",
    "Blaze detonation fires once per rotation — the 4s re-stack lockout "
    "prevents faster procs; timed fights still count one Blaze cycle "
    "(DoT + detonation) per fight",
    "Detonation % keeps its linear level scaling past 18 (12.35% at 19, "
    "12.71% at 20) per the parser array, not the wiki-prose 12% cap",
    "W is always Ablaze-empowered (a rotation opening with Q or E guarantees it)",
    "Ablaze ticks count as ability damage, keeping item burns "
    "(Liandry's Torment, Blackfire Torch) refreshed for the full 4s "
    "after Brand's last cast",
    "Q's sourced 1.75-second stun counts as target action downtime; E's "
    "spread doubling and R's slow remain utility-only",
]

SLOTS = {
    "Q": with_control(
        simple_damage(attr="Magic Damage", dmg_type="magic"),
        kind="stun",
        duration_attr="Stun Duration",
        effect_index=1,
    ),
    "W": simple_damage(attr="Increased Damage", dmg_type="magic"),
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": _pyroclasm,
    "P": _blaze,  # after the damage slots: reads their emissions
}

parse_abilities = build_parser(SLOTS, "Brand")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Brand",
        "revision_id": 4023911,
        "revision_timestamp": "2026-05-30T00:40:25Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
