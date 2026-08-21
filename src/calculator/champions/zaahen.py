"""Zaahen — CP10.10 full-entry-reviewed packet module.

Wiki-sourced item on-hit application is attached as a post-process on the
batch parser output (the batch parser builds its slot map at build time, so
declarations cannot be injected into the slot dict after the fact).

Row-selection fix (W): Dreaded Return "extends his glaive in the target
direction, dealing physical damage to enemies hit.  Upon reaching maximum
range, all enemies hit are dealt physical damage".  The generated packet
priced only the first leg — "Initial Physical Damage"
(40/60/80/100/120 + 50% bonus AD) — dropping the "Subsequent Physical
Damage" row (30/50/70/90/110 + 30% bonus AD).  This module prices the
cache's "Total Physical Damage" (70/110/150/190/230 + 80% bonus AD),
which is the two summed.  Two legs is not one hit, so W declares its
aggregate at the cast boundary instead of certifying a single hit; the
glaive's travel time to maximum range is not in the entry, so the second
leg's offset is left for the timing wave.

P (Cultivation of War) is the Determination stack buff: "for each stack,
Zaahen gains bonus attack damage equal to 1.5% : 2.95% (based on level)
AD.  At maximum stacks ... double the bonus to 36% : 70.87%".  Both
percentages are cached per-level rows and the stack count is an explicit
option (default 12, the sourced maximum), because the request carries no
stack state.  The BUFF phase puts the bonus AD into the parse context,
so Q/W/E/R's own %AD and %bonus-AD ratios scale off it.  The passive's
other half — a once-per-cooldown resurrection at maximum stacks — is the
revive axis, which ``starting_revive_defense`` states only for a fight's
opening health, not a mid-fight trigger.
"""

from functools import partial
from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .inputs import champion_stat
from .engine import BUFF, SlotCtx
from .healing_contract import declare_healing_rule
from .module_helpers import typed_damage
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
    with_item_on_hits,
)

PACKET_SHA256 = "5f5796aa0364becd253cbb3b7b05939147841a3f76e41cfa061242d344ec9f63"

# Grim Deliverance's damage is the slam's, not the launch's: "He then slams
# his glaive down after a 0.6-second delay, unleashing a shockwave that
# deals physical damage to nearby enemies" (cached R prose).
_R_SLAM_DELAY_SECONDS = 0.6

# HARDCODED: verify on patch updates — Determination's 12-stack cap is
# cached P prose ("stacking up to 12 times"), and the two Per-Level
# Scaling rows are ordered per-stack first, filled-at-maximum second.
_P_MAX_STACKS = 12
_P_PER_STACK_OCCURRENCE = 0
_P_MAX_STACK_OCCURRENCE = 1


def _determination_percent(ctx: SlotCtx, occurrence: int) -> float:
    """One of Cultivation of War's two Per-Level Scaling rows, in percent."""
    ability = ctx.ability("P")
    leveling = find_named_leveling(ability, "Per-Level Scaling", occurrence=occurrence)
    if leveling is None:
        # A silent zero would erase the passive — fail loudly instead.
        raise ValueError(
            f"Zaahen P: 'Per-Level Scaling' leveling entry #{occurrence} "
            "(per-stack / filled Determination) missing from the ability JSON"
        )
    return sum_modifiers(leveling, ctx.level, level=ctx.level)


def _cultivation_of_war(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Determination's bonus AD, doubled once the 12th stack lands."""
    ability = ctx.ability("P")
    if ability is None:
        return None

    stacks = min(max(int(ctx.option("p_determination_stacks")), 0), _P_MAX_STACKS)
    per_stack = _determination_percent(ctx, _P_PER_STACK_OCCURRENCE)
    filled = _determination_percent(ctx, _P_MAX_STACK_OCCURRENCE)
    percent = filled if stacks >= _P_MAX_STACKS else per_stack * stacks
    bonus_ad = percent / 100.0 * ctx.stat("attack_damage")
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus_ad
    entry = damage_entry(
        ability.get("name", "Cultivation of War"),
        ctx.level,
        0.0,
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_damage": bonus_ad}
    entry["detail"] = (
        f"{stacks}/{_P_MAX_STACKS} Determination stack(s) = {percent:g}% "
        f"AD (+{bonus_ad:.2f} bonus attack damage); at maximum stacks the "
        f"per-stack {per_stack:g}% row is replaced by the filled "
        f"{filled:g}% row.  The maximum-stack resurrection is the revive "
        "axis, which has no mid-fight channel"
    )
    return entry


_cultivation_of_war.phase = BUFF


def _darkin_glaive(ctx: SlotCtx) -> dict[str, Any] | None:
    """Price the selected Q row from Zaahen's three sourced Q variants."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    try:
        variant = int(ctx.option("q_variant"))
    except (TypeError, ValueError):
        variant = 0
    variant = max(0, min(variant, 2))
    attributes = (
        "Total Physical Damage",
        "Physical Damage per Hit",
        "Bonus Physical Damage",
    )
    attribute = attributes[variant]
    sourced_amount = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    count = 2 if variant < 2 else 1
    amount = sourced_amount / 2.0 if variant == 0 else sourced_amount
    entry = damage_entry(
        ability.get("name", "The Darkin Glaive"),
        rank,
        extract_cooldown(ability, rank),
        sourced_amount if variant != 1 else sourced_amount * count,
        "physical",
    )
    # The knock-up is a property of the variant, not of the slot, so it is
    # authored here rather than in MODULE_CC: variants 0 and 1 price the
    # first cast, whose two strikes only "deal modified physical damage",
    # while variant 2's "Bonus Physical Damage" is the recast, which alone
    # "knock[s] up the target for 0.75 seconds".
    entry["parts"] = (
        DamagePart(
            "physical",
            amount=amount,
            count=count,
            time_offset=0.0,
            hit_interval=0.0,
            cc_kind="knockup" if variant == 2 else "none",
        ),
    )
    entry["detail"] = f"Q variant: {attribute}."
    return entry


_darkin_glaive.phase = "damage"


def _dreaded_return(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the extension plus the maximum-range hit, declared at the cast."""
    return typed_damage(ctx, "Total Physical Damage", "physical", time_offset=0.0)


# Dreaded Return's glaive reaches its end and "all enemies hit are dealt
# physical damage, stunned for 0.25 seconds, and pulled 225 units toward
# Zaahen" — the cast stuns the target it damages, and the row now prices
# both of the cast's legs.  Aureate Rush only flourishes, and Grim
# Deliverance's shockwave only slams.  Q is not here: its knock-up belongs
# to the recast variant, so the kind is authored per part in
# ``_darkin_glaive``.  P is the Determination stack buff and authors no
# damage part.
MODULE_CC = {"W": "stun", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zaahen",
    PACKET_SHA256,
    assumption_overrides=(
        "The Darkin Glaive prices both strikes (Physical Damage per Hit x 2 "
        "== Total Physical Damage).",
        "Dreaded Return prices both legs — the cached Total Physical "
        "Damage row (70/110/150/190/230 + 80% bonus AD) == Initial "
        "Physical Damage + Subsequent Physical Damage.  The generated "
        "packet priced the Initial leg alone.  The aggregate is declared "
        "at the cast boundary; the glaive's travel to maximum range is "
        "not authored.",
    ),
    # E's flourish is one hit at the cast; its packet carries no travel or
    # tick phase to place.  W prices two legs and declares their aggregate
    # at the cast instead.
    single_hit_slots=frozenset({"E"}),
    # "He then slams his glaive down after a 0.6-second delay, unleashing a
    # shockwave that deals physical damage" — R's hit is the slam's.
    packet_part_timings={"R": {"time_offset": _R_SLAM_DELAY_SECONDS}},
    slot_parsers={
        "Q": _darkin_glaive,
        "W": _dreaded_return,
        "P": _cultivation_of_war,
    },
    slot_wrappers={
        "Q": partial(
            with_item_on_hits, effectiveness=1.0, hits=1, triggers=("on_hit",)
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "q_variant",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "Q damage variant",
    },
    {
        "key": "p_determination_stacks",
        "type": "int",
        "default": _P_MAX_STACKS,
        "min": 0,
        "max": _P_MAX_STACKS,
        "label": ("Determination stacks (12 = filled, which doubles the bonus)"),
        "rotation": {
            "role": "self_state",
            "slot": "P",
            "note": (
                "Stacks Zaahen's own attacks and abilities generate; the "
                "buff is self-state, not a consumed setup."
            ),
        },
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Cultivation of War) grants bonus attack damage equal to the "
    "cached per-level Determination row (1.5% : 2.95% AD) per stack, "
    "replaced at the 12-stack cap by the filled row (36% : 70.87% AD).  "
    "p_determination_stacks (default 12, the sourced maximum) is the "
    "stack state the request does not carry; the buff reaches the parse "
    "context before Q/W/E/R, so their AD ratios scale off it.",
    "The passive's maximum-stack resurrection — 4 seconds of "
    "invulnerability restoring 30-75% of maximum health — is not "
    "priced: the revive axis states a fight's opening health, not a "
    "mid-fight trigger.",
]


# No MODULE_COVERAGE: every one of the five slots emits a priced row now.


# pylint: disable=protected-access,too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Zaahen self-healing events from its authored packet."""
    healing = []
    # The Darkin Glaive (Q): the empowered attack heals him for "Champion
    # Healing" — 5/6/7/8/9% of his maximum health (halved against
    # minions/monsters; champion targets assumed).  The Wiki unit ("% of
    # his maximum health") is not a slotlib-recognised unit, so the percent
    # is read raw and priced against the sourced max health.
    q_rank = _healing._rank(ability_damages, "Q")
    q_heal_pct = _healing._leveling_value(
        _healing._ability(champion_data, "Q"), "Champion Healing", q_rank
    )
    q_heal = q_heal_pct / 100.0 * champion_stat(champion_stats, "health")
    # One payment per cast: the empowered attack strikes twice and the
    # cache grants one heal, and the heal lands on-attack even when the
    # paired strike packet was fully blocked.
    for payment in _healing._payments(
        _healing.HealAnchor.CAST, "Q", damage_events, cast_timeline
    ):
        _healing._heal_from_damage(
            healing,
            payment.event,
            q_heal,
            "The Darkin Glaive",
            link_to_damage=False,
        )
    # Grim Deliverance (R): flat heal per champion hit
    # ("Healing per Champion hit": 82.5 / 132 / 181.5 (+ 66% bonus
    # AD)); the 1v1 pair fight sees exactly one hit per R cast.
    r_rank = _healing._rank(ability_damages, "R")
    r_heal = _healing.extract_named(
        _healing._ability(champion_data, "R"),
        "Healing per Champion hit",
        r_rank,
        champion_stats,
        {},
    )
    for payment in _healing._payments(
        _healing.HealAnchor.CAST, "R", damage_events, cast_timeline
    ):
        _healing._heal_from_damage(
            healing,
            payment.event,
            r_heal,
            "Grim Deliverance",
            link_to_damage=False,
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Zaahen", derive_self_healing)
