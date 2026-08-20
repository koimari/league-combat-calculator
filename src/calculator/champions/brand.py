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
from ..cast_dependency import CastDependency
from .engine import SlotCtx, build_parser
from .module_helpers import delayed_damage
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    pct_health_per_hit,
    simple_damage,
)

# HARDCODED: verify on patch updates — the Ablaze DoT is prose-only in
# the JSON (P effect[1] has no leveling entry): each stack deals 2% of
# the target's maximum health as magic damage over 4 seconds.
# https://wiki.leagueoflegends.com/en-us/Brand
_ABLAZE_DOT_PCT_MAX_HP = 0.02  # per stack, full 4 s burn

_ABLAZE_DURATION_S = 4.0  # every tick is ability damage: refreshes item burns
_ABLAZE_MAX_STACKS = 3
_R_MAX_BOUNCES = 3

# Pillar of Flame erupts on its own delay, and the cached note fixes the
# offset's origin for us: "After a 0.627 seconds delay, Brand erupts a
# pillar of flame at the target location that deals magic damage to
# enemies hit", with "The delay before the eruption does not include the
# cast time. The delay would be a total of 0.891 seconds if it included
# the cast time."  ``time_offset`` is measured from the cast start, so the
# sourced total is the number to author.
_W_ERUPTION_FROM_CAST_START_S = 0.891


def _r_bounces(ctx: SlotCtx) -> int:
    """Pyroclasm bounces hitting the target, clamped to the in-game 1-3."""
    return max(1, min(_R_MAX_BOUNCES, int(ctx.option("r_bounces"))))


def _pyroclasm(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: per-bounce damage x the r_bounces option (never the JSON total)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    per_bounce = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    total = per_bounce * _r_bounces(ctx)
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
            count=_r_bounces(ctx),
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
        applications += _r_bounces(ctx)
    if applications < 1:
        return None

    max_hp = ctx.target_stat("target_max_health")
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
            ap=ctx.stat("ability_power"),
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
    "Q's stun, E's spread doubling, and R's slow are utility-only and "
    "excluded from damage",
]

# Cached kit review.  E "creates a blast that deals magic damage" and its
# Ablaze Bonus only doubles the spread range; W's eruption "deals magic
# damage to enemies hit" and its Ablaze Bonus is "The target takes 25%
# increased damage" — no control on either, either way.
#
# Q and R stay UNREVIEWED, so this kit keeps the coarse control-armed
# scan, and the reason is not timing: Q's stun and R's slow are both
# "Ablaze Bonus" branches, so whether a cast controls depends on the
# target's stack state at that cast, not on the slot.  The rotation's
# opening Q is the applier and stuns nothing; every later one does.  One
# kind per slot cannot say both, and Q additionally authors no event
# (its fireball has no sourced travel time).  P is the Ablaze burn row.
MODULE_CC = {"E": "none", "W": "none"}

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": delayed_damage(
        delay=_W_ERUPTION_FROM_CAST_START_S,
        attr="Increased Damage",
        dmg_type="magic",
    ),
    # One blast on the target Brand sets aflame, landing at the cast.
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _pyroclasm,
    "P": _blaze,  # after the damage slots: reads their emissions
}

# The revision this declaration was read from, in the shape
# scripts/cast_dependency_audit.py will resolve against the committed
# wiki audit once this phase's audit slice lands -- that script is not
# in the tree yet, so today this string is shape-checked and pinned
# equal to SOURCES by test, nothing more. It is the same parent entry
# SOURCES publishes below.
_WIKI_SOURCE = "https://wiki.leagueoflegends.com/en-us/Brand@4023911"

# Head only (D-89). Q opening is the mechanic below; the rest of the seed
# order — R and E between Q and W — is a stack-count and DPS preference,
# so the resolver's hand seed keeps it. One edge, not three: R and E apply
# Ablaze too, so this is the minimal declaration that keeps W's priced
# row true in every derived order, and naming the other appliers as well
# would constrain more than the mechanic does.
CAST_DEPENDENCIES = (
    CastDependency(
        slot="W",
        requires="Q",
        kind="damage_enabler",
        reason=(
            "W is priced at its Ablaze-empowered row: this module reads "
            "'Increased Damage', which is Blaze's 'Ablaze Bonus: the "
            "target takes 25% increased damage' and exists only against a "
            "target already afflicted. Q is the rotation's opener and "
            "applies the stack ('Brand's abilities apply a stack of "
            "Ablaze to enemies hit'), so an order that casts W first "
            "prices a bonus nothing set up."
        ),
        source=_WIKI_SOURCE,
    ),
)

parse_abilities = build_parser(SLOTS, "Brand", cc_kinds=MODULE_CC)


SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Brand",
        "revision_id": 4023911,
        "revision_timestamp": "2026-05-30T00:40:25Z",
    }
]
