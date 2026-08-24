"""Yasuo — Gathering Storm (Q3) and Ride the Wind (E) stack systems.

Stack mechanics modeled (E3):
- Q (Steel Tempest): Gathering Storm stacks up to 2 (6-second window).
  At 2 stacks the next Q cast consumes them to become the Q3 whirlwind.
  The whirlwind deals the SAME sourced damage as a normal Q — the
  empower is a 0.9-second knockup (CC state, not damage). ``q_gathering_storm``
  is the explicit pre-stack state.
- E (Sweeping Blade): Ride the Wind stacks up to 4 on the target. Each
  stack adds the sourced "Bonus Damage per Stack" (17.5 : 32.5 by rank
  + 5% bonus AD + 15% AP), so E at N stacks prices base + N x per-stack;
  at 4 stacks this equals the wiki "Total Combined Damage".
- P (Way of the Wanderer): Flow shield (125 : 674.46 by level) is a
  state row; crit conversion and reduced crit damage are passive stats.

- W (Wind Wall) is a selected projectile-defense window: the cached
  active duration, the slots (or specific incoming event ids) the
  scenario names, and nothing else.  R (Last Breath) keeps the reviewed
  CP10.10 packet pricing.  All numeric values are read from the champion
  JSON data.

Coverage: P and W are ``no_damage``, not ``out_of_scope``.  Way of the
Wanderer deals nothing — it grants the Flow shield and the crit
conversion the fight engine already applies through ``crit_modifier`` —
and Wind Wall only destroys projectiles.  Q, E and R each price their
own row — R (Last Breath) among them: the map dropped it while its SLOTS
entry was never touched (the Samira precedent), which is the stale label
this fixes.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx
from .module_helpers import (
    CRIT_CHANCE_MULTIPLIER,
    CRIT_DAMAGE_MULTIPLIER_FACTOR,
    EXCESS_CRIT_BONUS_AD_PER_PERCENT,
    crit_conversion_certification,
    crit_conversion_payload,
    no_damage,
    q3_knockup_duration,
)
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_description_duration,
    extract_named,
    extract_value,
)
from .inputs import bool_option, float_option, int_option
from .module_contract import coverage

PACKET_SHA256 = "94e34c2bf9df12ee71c952261d6c8ca2d69773f4e5eb2fc218cd944bada606ac"


# P4: the crit-conversion rule is the shared module_helpers rule (the
# 0.9 factor's atom hash is f375a24fbf0555e1 for Yasuo).
(
    _CRIT_CHANCE_MULTIPLIER,
    _CRIT_DAMAGE_MULTIPLIER_FACTOR,
    _EXCESS_CRIT_BONUS_AD_PER_PERCENT,
) = (
    CRIT_CHANCE_MULTIPLIER,
    CRIT_DAMAGE_MULTIPLIER_FACTOR,
    EXCESS_CRIT_BONUS_AD_PER_PERCENT,
)
CERTIFIED_CONSTANTS, ATOM_IDS = crit_conversion_certification("f375a24fbf0555e1")
certified_constants, atom_ids = CERTIFIED_CONSTANTS, ATOM_IDS


def _way_of_the_wanderer(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Flow shield state row carrying the crit-conversion payload."""
    ability = ctx.ability()
    if ability is None:
        return None
    shield = extract_named(ability, "Bonus Damage", ctx.level, ctx.stats, ctx.target)
    entry = no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"Flow reaches 100 stacks (5900/5250/4600 units by level) to "
            f"grant a {shield:.2f} magic-damage shield for 1s.  Intent: "
            "total crit chance doubled (capped at 100%), crits deal 90% of "
            "the normal crit damage, and excess crit chance converts to "
            "bonus AD (0.5 per 1%) — applied by the fight engine to autos "
            "and Steel Tempest's crit-eligible AD portion."
        ),
    )
    entry["crit_modifier"] = crit_conversion_payload()
    entry["certified_constants"] = dict(CERTIFIED_CONSTANTS)
    entry["atom_ids"] = dict(ATOM_IDS)
    return entry


def _steel_tempest(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Steel Tempest, empowered into the Q3 whirlwind at 2 Gathering Storm stacks."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    stacks = min(max(int(ctx.option("q_gathering_storm")), 0), 2)
    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    # "Steel Tempest's damage based on its AD ratio can critically strike"
    # (cached Q description): the flat 20-120 base never crits, so it is a
    # plain part; the 105% AD portion is a separate crit-eligible part that
    # uses the crit chance/multiplier the engine resolves from P's
    # crit_modifier (which already multiplies the multiplier by 0.9).
    flat = extract_value(ability, "Physical Damage", rank, 0)
    ad_ratio = extract_value(ability, "Physical Damage", rank, 1) / 100.0
    ad_part = ctx.stat("attack_damage") * ad_ratio
    # Both parts are the one thrust — the split is crit eligibility, not a
    # second hit — so the ledger sees ONE landing: the flat part carries
    # the cast instant (and with it the control marker), and the AD part
    # rides that same event rather than booking a second one.
    #
    # The knock-up is a property of the branch, not of the slot, so it is
    # authored here rather than in MODULE_CC: only the 2-stack cast is the
    # whirlwind that "additionally knocks up enemies hit for 0.9 seconds",
    # and that sentence is where its duration is read from.
    knockup = q3_knockup_duration("Yasuo", ability) if stacks >= 2 else 0.0
    entry["parts"] = (
        DamagePart(
            "physical",
            flat,
            time_offset=0.0,
            cc_kind="knockup" if stacks >= 2 else "none",
            cc_duration=knockup,
        ),
        DamagePart("physical", ad_part, crit_effectiveness=1.0),
    )
    if stacks >= 2:
        entry["detail"] = (
            "Gathering Storm at 2 stacks: this cast is the Q3 whirlwind — "
            f"same sourced damage as a normal thrust, adding a {knockup:g}s "
            "knock-up (crowd-control state, not damage)."
        )
    else:
        entry["detail"] = (
            f"Gathering Storm {stacks}/2 stacks; the Q3 whirlwind at 2 "
            "stacks deals the same sourced damage (the empower is the "
            "knock-up, a crowd-control state)."
        )
    return entry


def _wind_wall(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: expose Wind Wall as a selected projectile-defense atom."""
    ability = ctx.ability()
    rank = ctx.rank_for()
    if ability is None or rank < 1:
        return None
    active = bool(ctx.option("w_active"))
    duration = extract_description_duration(ability)
    if duration is None:
        return None
    selected_duration = float(ctx.option("w_active_seconds") or 0.0)
    if selected_duration > 0.0:
        duration = min(duration, selected_duration)
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "total_raw": 0.0,
        "damage_type": "magic",
        "parts": (),
        "defensive_interaction": {
            "kind": "yasuo_wind_wall",
            "active": active,
            "duration": duration if active else 0.0,
            "blocked_sources": list(ctx.option("w_blocked_skillshots")),
        },
        "detail": (
            "Wind Wall destroys selected marked projectiles during the "
            f"active window. Source duration: {duration:g}s."
        ),
    }


def _per_target_lockout(ability: dict[str, Any], rank: int) -> float:
    """Sweeping Blade's per-target cooldown (10/9/8/7/6 by rank)."""
    raw = str(ability.get("onTargetCdStatic") or "")
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if parts:
        return float(parts[min(max(rank - 1, 0), len(parts) - 1)])
    return float(extract_cooldown(ability, rank) or 0.5)


def _sweeping_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Sweeping Blade with Ride the Wind per-stack bonus damage.

    Single-target fight model: the 0.1s ability cooldown is irrelevant to
    a one-target fight because Sweeping Blade can only hit the same target
    once per its per-target lockout (``onTargetCdStatic``, 10/9/8/7/6 by
    rank); that lockout is the cast-rate limiter here.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    stacks = min(max(int(ctx.option("e_stacks")), 0), 4)
    base = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_named(
        ability, "Bonus Damage per Stack", rank, ctx.stats, ctx.target
    )
    total = base + stacks * per_stack
    lockout = _per_target_lockout(ability, rank)
    entry = damage_entry(
        ability_name(ability),
        rank,
        lockout,
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total),)
    # One impact at the end of the dash — the cached packet has no separate
    # travel or tick phase to place.
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"Ride the Wind {stacks}/4 stacks: base {base:.2f} + {stacks} x "
        f"per-stack bonus {per_stack:.2f} = {total:.2f}; at 4 stacks this "
        "equals the wiki Total Combined Damage (25% per stack, +100% at "
        f"maximum stacks).  Single-target cast rate: one dash per "
        f"{lockout:g}s per-target lockout."
    )
    return entry


# Sweeping Blade only "deals magic damage to the target"; Last Breath
# "knocks up all nearby airborne enemy champions for 1 second ... slashing
# them with his sword over the duration to deal physical damage".  Q is not
# here: its knock-up belongs to the Gathering Storm branch, so the kind is
# authored per part in ``_steel_tempest``.  W raises a projectile wall and P
# is the Flow/crit state row; neither authors a damage part.
MODULE_CC = {"Q": CC_PER_PART, "E": "none", "R": "knockup"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    # R's slashes are one priced sweep over the knock-up's duration.
    "Yasuo",
    PACKET_SHA256,
    assumption_overrides=(
        "Q3 (Gathering Storm at 2 stacks) deals the same sourced damage as a normal Q. Its 0.9s "
        "knock-up is an authored control interval on the cast's parts.",
        "E (Sweeping Blade) prices Ride the Wind stacks: base + N x per-stack bonus, capped at 4 "
        "stacks (the wiki Total Combined Damage)",
        "P (Way of the Wanderer) Intent is now priced: total crit chance is doubled (capped at "
        "100%), crits deal 90% of the normal crit damage, and excess crit chance converts to 0.5 "
        "bonus AD per 1% — applied by the fight engine to autos and Steel Tempest's crit-eligible "
        "AD part. The Flow shield stays state (no enemy damage)",
        "Q (Steel Tempest) splits the flat 20-120 base (never crits) from the 105% AD portion "
        "(crits at the converted crit stats, per the cached description 'damage based on its AD "
        "ratio can critically strike')",
        "W (Wind Wall) uses the cached active-duration value as a selected projectile-defense "
        "window. The scenario can name source slots, specific event ids (w_blocked_event_ids), or "
        "leave the lists empty for every marked projectile. Event ids are positional per scenario "
        "('attacker:defender:index'); changes to the build, ranks, or roster renumber them, and "
        "any selected id that never matches an incoming event is reported on the survival receipt "
        "as blocked_event_ids_unmatched. R (Last Breath) keeps the reviewed CP10.10 packet "
        "pricing.",
    ),
    single_hit_slots=frozenset({"R"}),
    slot_parsers={
        "P": _way_of_the_wanderer,
        "Q": _steel_tempest,
        "W": _wind_wall,
        "E": _sweeping_blade,
    },
    slot_order=("P", "Q", "W", "E", "R"),
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    int_option(
        "q_gathering_storm",
        0,
        minimum=0,
        maximum=2,
        label="Gathering Storm stacks (2 = Q3 ready)",
    ),
    int_option("e_stacks", 0, minimum=0, maximum=4, label="Ride the Wind stacks"),
    bool_option(
        "w_active", False, label="W (Wind Wall) active against selected skillshots"
    ),
    float_option(
        "w_active_from",
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="W active start time in seconds",
    ),
    float_option(
        "w_active_seconds",
        0.0,
        minimum=0.0,
        maximum=4.0,
        label="W active seconds; zero uses the source duration",
    ),
    {
        "key": "w_blocked_skillshots",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Skillshot slots to block; an empty list blocks all marked " "skillshots"
        ),
    },
    {
        "key": "w_blocked_event_ids",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Specific incoming event ids to destroy (e.g. "
            "'main:enemy:Yasuo:1'). Event ids are positional per "
            "scenario: builds, ranks, or roster changes renumber them. "
            "An empty list blocks nothing by event id."
        ),
    },
]


MODULE_COVERAGE = coverage(no_damage="PW")
