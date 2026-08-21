"""Bard — slot map for the archetype engine.

Why each slot is non-generic:
- P (Traveler's Call) is a custom fn: the JSON entry has ZERO
  effects/leveling (known-degraded parse — CLAUDE.md Known Quirks), so
  the meep formula lives as wiki-sourced module constants. Meep damage
  scales with a chime-counter champion option, and meep AVAILABILITY is
  a stock + recharge model — the emitted on-hit carries ``max_procs`` =
  stock + floor(fight_duration / recharge), so the fight engine
  empowers only that many autos; the rest are plain.
- Q (Cosmic Binding) parses generically ("Magic Damage" is exactly
  right); pinned to the explicit attr so a JSON reshuffle can't move
  it. The slow/stun is CC with no damage component.
- W (Caretaker's Shrine) is an ally-only heal: a zero-damage cast whose
  only job is to exist, so the rotation casts it and the ally-support
  scanner prices the sourced heal (200.0 to one teammate at rank 5, 0 AP,
  the cached "Maximum Heal" row).  The 5-second charge that separates that
  row from "Minimum Heal" is the boundary; the shrine is priced at full
  power.  No enemy-damage row exists: the cached W leveling carries only
  Minimum Heal / Maximum Heal / Bonus Movement Speed.
- E (Magical Journey) is a one-way terrain portal: every effect row in
  the cached JSON carries an empty ``leveling`` list and the ability has
  no ``damageType`` — zero damage, confirmed against data/champions.json.
  The travel itself stays unpriced on the terrain axis, which the fight
  engine does not model at all.
- R (Tempered Fate) is 2.5s stasis; the cached notes are explicit —
  "Tempered Fate deals 0 proc true damage" — atoms-confirmed zero
  numeric combat effect, not merely an assumption.  The stasis magnitude
  stays unpriced: ``ability_spec.cc_kind`` is one vocabulary string per
  part with no duration and no percent, so a stasis can be declared but
  never priced.

Roadmap session 2 (2026-08-20): E and R emit an explicit, user-visible
zero-damage row via ``module_helpers.no_damage`` instead of staying
silently absent, and ``MODULE_COVERAGE`` calls them ``no_damage`` rather
than letting ``SLOTS`` derive ``modeled``.
"""

from typing import Any

from .engine import ONHIT, SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import (
    ability_on_hit_entry,
    simple_damage,
    support_cast,
    with_control,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — Bard's P[0] "Traveler's Call" has
# no effects/leveling in the wiki JSON at all (known-degraded parse), so
# every passive number below is wiki prose:
# https://wiki.leagueoflegends.com/en-us/Bard
# Meep on-hit damage: 30 (+6 per 5 chimes) (+40% AP) magic damage.
_MEEP_BASE = 30.0
_MEEP_PER_TIER = 6.0
_CHIMES_PER_TIER = 5
_MEEP_AP_RATIO = 0.40

# Meep stock and recharge time are INDEPENDENT chime-breakpoint tables,
# (min_chimes, value) checked top-down. Verbatim wiki pp templates:
#   stock:    {{pp|1 to 9 for 9|0;10;30;50;65;80;90;95;100}}
#   recharge: {{pp|8 to 4 for 5|0;20;40;55;70}}
# Stock caps at the 100-chime breakpoint (9 meeps), recharge at 70 (4s);
# the damage formula above is uncapped (+6 per 5 chimes continues).
_MEEP_STOCK_TIERS = (
    (100, 9),
    (95, 8),
    (90, 7),
    (80, 6),
    (65, 5),
    (50, 4),
    (30, 3),
    (10, 2),
    (0, 1),
)
_MEEP_RECHARGE_TIERS = (
    (70, 4.0),
    (55, 5.0),
    (40, 6.0),
    (20, 7.0),
    (0, 8.0),
)

_DEFAULT_CHIMES = 35


class _TravelersCallRule:
    """The typed Traveler's Call (chimes + meeps) declaration (P3 package 3Y).

    Chimes are a PERMANENT counter seeded by the user — the model cannot
    simulate map chime spawning/collection (no engine stream) — so the
    seed prices the meep math at parse time.  Meep AVAILABILITY is a
    consumable fight-window resource (stock + floor(duration / recharge))
    priced into the P on-hit's ``max_procs``; each meep-empowered auto
    consumes one meep.  ``public_receipt()`` rides the option's state
    and the resource-ledger chimes declaration.
    """

    def __init__(self) -> None:
        self.meep_base = _MEEP_BASE
        self.meep_per_tier = _MEEP_PER_TIER
        self.chimes_per_tier = _CHIMES_PER_TIER
        self.meep_ap_ratio = _MEEP_AP_RATIO
        self.stock_tiers = list(_MEEP_STOCK_TIERS)
        self.recharge_tiers = list(_MEEP_RECHARGE_TIERS)
        self.permanent = True
        # The revision has one home (the champion source receipt); only the
        # label narrows it to the prose this rule reads.
        self.source = {
            **load_champion_sources("Bard")[0],
            "label": "Local League Wiki cache — Bard P (Traveler's Call) prose",
        }

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "Bard — Traveler's Call (Chimes + Meeps)",
            "meep_base": self.meep_base,
            "meep_per_tier": self.meep_per_tier,
            "chimes_per_tier": self.chimes_per_tier,
            "meep_ap_ratio": self.meep_ap_ratio,
            "stock_tiers": self.stock_tiers,
            "recharge_tiers": self.recharge_tiers,
            "permanent": self.permanent,
            "source": dict(self.source),
        }


BARD_TRAVELERS_CALL_RULE = _TravelersCallRule()


def _tier_value(tiers: tuple, chimes: int) -> Any:
    """Value of the highest breakpoint the chime count has reached."""
    return next(value for threshold, value in tiers if chimes >= threshold)


def _travelers_call(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: meep on-hit magic damage, applications capped by stock + recharge."""
    ability = ctx.ability()
    if ability is None:
        return None

    chimes = max(0, int(ctx.options.get("chimes", _DEFAULT_CHIMES)))
    ap = ctx.stat("ability_power")
    per_meep = (
        _MEEP_BASE + _MEEP_PER_TIER * (chimes // _CHIMES_PER_TIER) + _MEEP_AP_RATIO * ap
    )

    stock = _tier_value(_MEEP_STOCK_TIERS, chimes)
    recharge = _tier_value(_MEEP_RECHARGE_TIERS, chimes)
    # Timed fights recharge meeps over the window; one-rotation mode and
    # direct parse calls model the stocked meeps only.
    fight_duration = ctx.options.get("fight_duration_seconds")
    recharges = int(float(fight_duration) // recharge) if fight_duration else 0

    name = ability.get("name", "Traveler's Call")
    return ability_on_hit_entry(
        name,
        ctx.level,
        "magic",
        {
            "name": f"{name} (Meep)",
            "damage_per_hit": per_meep,
            "damage_type": "magic",
            "max_procs": stock + recharges,
        },
    )


_travelers_call.phase = ONHIT


def _magical_journey(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: one-way terrain portal — documented zero-damage row."""
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability.get("name", "Magical Journey"),
        reason=(
            "Magical Journey opens a one-way terrain portal; every effect "
            "row in the cached entry carries empty leveling and the "
            "ability has no damage type (data/champions.json Bard E). "
            "Confirmed zero numeric combat effect."
        ),
    )


def _tempered_fate(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: 2.5s stasis/stun — documented zero-damage row."""
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability.get("name", "Tempered Fate"),
        reason=(
            "Tempered Fate puts struck units into 2.5s stasis and stuns "
            "enemy champions/minions/turrets for the same duration; the "
            "cached entry's own notes state Tempered Fate deals 0 proc "
            "true damage (data/champions.json Bard R notes). "
            "Atoms-confirmed zero numeric combat effect."
        ),
    )


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "chimes",
        "type": "int",
        "default": _DEFAULT_CHIMES,
        "label": "Chimes collected",
        "min": 0,
        "max": 200,
        "state": BARD_TRAVELERS_CALL_RULE.public_receipt(),
    },
]

ASSUMPTIONS = [
    "Meep availability is stock + recharge: min(autos, stock + "
    "fight_duration / recharge) autos are meep-empowered; remaining "
    "autos are plain (one-rotation mode uses stocked meeps only)",
    "Meep damage formula is uncapped (+6 per 5 chimes continues); stock "
    "caps at the 100-chime breakpoint (9 meeps), recharge at 70 (4s)",
    "Meep slow and the 15+ chime AoE/cone splash are not modeled — "
    "single-target calculator; the splash never hits the primary target",
    "Q counted as a single hit on the primary target; the slow/stun is "
    "CC with no damage component",
    "W (heal), E (portal), and R (stasis) deal no enemy damage. W is "
    "cast so the ally-support scanner can price its sourced heal at the "
    "fully-charged shrine; E and R emit an explicit zero-damage state "
    "row (no_damage) rather than staying absent from the breakdown, "
    "with the portal's travel and the stasis magnitude left unpriced",
]

SLOTS = {
    "P": _travelers_call,
    # The bolt "deals magic damage to the first enemy hit" once, at the
    # cast — the 300-unit continuation only reaches a second target.  The
    # cached "Disable Duration" row (1-1.8s) sits in the same effect as
    # that first hit, so it is the SLOW's duration here; the stun the
    # second effect describes lasts "the same duration".
    "Q": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Disable Duration",
    ),
    # Caretaker's Shrine heals the ally who walks over it.  The slot exists
    # so the rotation casts it and the support scanner can price the shrine
    # at full power (cached "Maximum Heal", 50-200 + 70% AP); the 5-second
    # charge that separates it from "Minimum Heal" is the boundary.
    "W": support_cast(
        default_name="Caretaker's Shrine",
        detail="Ally heal (sourced by the support scanner) at the "
        "fully-charged shrine; the 5s charge ramp is not modeled.",
    ),
    "E": _magical_journey,
    "R": _tempered_fate,
}

# Cached kit review.  Q "slows [the first enemy hit] by 60% for a
# duration"; the stun it can add needs the bolt to go on and hit "terrain
# or a second enemy", which the single-target model never supplies, so the
# slow is the answer for the target Q damages here.  W, E and R deal no
# damage, and P's Meep slow rides basic attacks rather than an ability.
MODULE_CC = {"Q": "slow"}

parse_abilities = build_parser(SLOTS, "Bard", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Bard")

# E and R are emitted rows that price nothing, so the coverage they derive
# from SLOTS ("modeled") would overstate them.  W stays modeled: its own
# row prices no damage, but the ally-support scanner prices its sourced
# heal off the cast this slot schedules.
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "no_damage",
    "R": "no_damage",
}
