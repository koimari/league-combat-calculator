"""Bard: slot map for the archetype engine.

P (Traveler's Call) has zero cached effects and leveling, a known-degraded parse
TRAPS.md records, so the meep formula is wiki-sourced module constants.  Meep
damage scales with the chime option, and meep AVAILABILITY is a stock plus
recharge model: the emitted on-hit carries ``max_procs`` of stock plus
``floor(fight_duration / recharge)``, so only that many autos are empowered.
Q (Cosmic Binding) parses generically and is pinned to the explicit attribute so
a cache reshuffle cannot move it; its slow and stun carry no damage.
W (Caretaker's Shrine) is an ally-only heal.  The cast is a zero-damage row whose
job is to exist, so the rotation casts it and the support scanner prices the
cached "Maximum Heal" row; the 5-second charge separating that from "Minimum
Heal" is the boundary, and the shrine is priced at full power.
E (Magical Journey) is a one-way terrain portal with empty leveling on every
effect row; the travel stays unpriced on the terrain axis.
R (Tempered Fate) is stasis, and the cached notes say outright that it deals 0
proc true damage.  The stasis magnitude stays unpriced because
``ability_spec.cc_kind`` is one vocabulary string with no duration and no
percent, so a stasis can be declared but never priced.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, NamedTuple

from ..binary_roots import data_value, spell_object
from .charge_cadence import ChargeRule
from .contract_vocabulary import coverage
from .engine import ONHIT, SlotCtx, build_parser
from .inputs import int_option
from .module_helpers import ability_slot, no_damage_slot
from .shared_option_keys import BARD_CHIMES
from .slot_cc import CC_PER_PART
from .slot_control import with_control, with_control_event
from .slot_entries import ability_on_hit_entry, support_cast
from .slot_extract import ability_name
from .slotlib import simple_damage
from .source_receipts import load_champion_sources, state_receipt

# Bard's P[0] remains degraded in the wiki JSON, but the tracked
# BardPTooltip_D_nS record carries the passive tooltip values directly.
_BARD_P_SPELL = spell_object("Bard", "BardPTooltip_D_nS")
_MEEP_BASE = data_value(_BARD_P_SPELL, "BaseMeepDamage")
_MEEP_PER_TIER = data_value(_BARD_P_SPELL, "DamagePerCheckpoint")
_CHIMES_PER_TIER = int(data_value(_BARD_P_SPELL, "TooltipChimeDamageCheckpoint"))
_MEEP_AP_RATIO = data_value(_BARD_P_SPELL, "MeepAPRatio")
_MEEP_BASE_RECHARGE = data_value(_BARD_P_SPELL, "BaseMeepSpawnCD")

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
    (0, _MEEP_BASE_RECHARGE),
)

_DEFAULT_CHIMES = 35


class _TravelersCallRule(NamedTuple):
    """The typed Traveler's Call (chimes + meeps) declaration.

    Chimes are a PERMANENT counter seeded by the user, because the model
    cannot simulate map chime spawning and collection (no engine stream),
    so the seed prices the meep math at parse time.  Meep AVAILABILITY is
    a consumable fight-window resource (stock + floor(duration / recharge))
    priced into the P on-hit's ``max_procs``; each meep-empowered auto
    consumes one meep.  ``public_receipt()`` rides the option's state
    and the resource-ledger chimes declaration.
    """

    meep_base: float
    meep_per_tier: float
    chimes_per_tier: int
    meep_ap_ratio: float
    stock_tiers: tuple[tuple[int, int], ...]
    recharge_tiers: tuple[tuple[int, float], ...]
    permanent: bool
    source: Mapping[str, Any]

    def public_receipt(self) -> dict[str, Any]:
        """The published Traveler's Call declaration."""
        return state_receipt("Bard — Traveler's Call (Chimes + Meeps)", self)


BARD_TRAVELERS_CALL_RULE = _TravelersCallRule(
    meep_base=_MEEP_BASE,
    meep_per_tier=_MEEP_PER_TIER,
    chimes_per_tier=_CHIMES_PER_TIER,
    meep_ap_ratio=_MEEP_AP_RATIO,
    stock_tiers=_MEEP_STOCK_TIERS,
    recharge_tiers=_MEEP_RECHARGE_TIERS,
    permanent=True,
    # The revision has one home (the champion source receipt); only the
    # label narrows it to the prose this rule reads.
    source=MappingProxyType(
        {
            **load_champion_sources("Bard")[0],
            "label": "Local League Wiki cache — Bard P (Traveler's Call) prose",
        }
    ),
)


def _tier_value(tiers: tuple, chimes: int) -> Any:
    """Value of the highest breakpoint the chime count has reached."""
    return next(value for threshold, value in tiers if chimes >= threshold)


@ability_slot()
def _travelers_call(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: meep on-hit magic damage, applications capped by stock + recharge."""

    chimes = max(0, int(ctx.options.get(BARD_CHIMES, _DEFAULT_CHIMES)))
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

    name = ability_name(ability)
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


# E: one-way terrain portal — documented zero-damage row.
_magical_journey = no_damage_slot(
    "Magical Journey opens a one-way terrain portal; every effect "
    "row in the cached entry carries empty leveling and the "
    "ability has no damage type (data/champions.json Bard E). "
    "Confirmed zero numeric combat effect."
)


# R: 2.5s stasis/stun — documented zero-damage row.
_tempered_fate = no_damage_slot(
    "Tempered Fate puts struck units into 2.5s stasis and stuns "
    "enemy champions/minions/turrets for the same duration; the "
    "cached entry's own notes state Tempered Fate deals 0 proc "
    "true damage (data/champions.json Bard R notes). "
    "Atoms-confirmed zero numeric combat effect."
)


OPTIONS: list[dict[str, Any]] = [
    int_option(
        BARD_CHIMES,
        _DEFAULT_CHIMES,
        minimum=0,
        maximum=200,
        label="Chimes collected",
        state=BARD_TRAVELERS_CALL_RULE.public_receipt(),
        rotation={"role": "self_state", "slot": "P"},
    ),
]

ASSUMPTIONS = [
    "Meep autos are min(autos, stock + fight_duration / recharge), the rest plain; "
    "one rotation uses stock only.",
    "Meep damage is uncapped (+6 per 5 chimes); stock caps at 100 chimes (9 meeps) "
    "and recharge at 70 chimes (4s).",
    "Meep slow and the 15-chime cone splash are not modeled: single target, and the "
    "splash misses the primary.",
    "Q counted as a single hit on the primary target; the slow/stun is "
    "CC with no damage component",
    "W (heal), E (portal) and R (stasis) deal no enemy damage.",
    "W is cast so the ally-support scanner prices its sourced heal at the "
    "fully-charged shrine.",
    "E and R emit a no_damage row; the portal's travel and the stasis magnitude stay "
    "unpriced.",
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
    # Tempered Fate prices no damage; its stasis is the effect's own
    # window ("puts all units within into stasis for 2.5 seconds"), which
    # the cache carries as the slot's active-duration atom and in no
    # leveling row.
    "R": with_control_event(_tempered_fate, duration_source="active"),
}

# Cached kit review.  Q "slows [the first enemy hit] by 60% for a
# duration"; the stun it can add needs the bolt to go on and hit "terrain
# or a second enemy", which the single-target model never supplies, so the
# slow is the answer for the target Q damages here.  W, E and R deal no
# damage, and P's Meep slow rides basic attacks rather than an ability.
MODULE_CC = {"Q": "slow", "R": "stasis", "P": CC_PER_PART, "W": "none", "E": "none"}


# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "W": ChargeRule(
        why=(
            "W (Caretaker's Shrine) banks shrines on its cached 18s "
            "rechargeRate; the cached cooldown is the gap between "
            "placing two. The cached stock of 2 is not spent here: a "
            "shrine's heal is priced AT THE CAST, so the cast is the hit "
            "and the persistent-object exemption does not reach it: that "
            "exemption is for a cast whose object the module prices "
            "separately. The sourced stock is spent here. The field cap is "
            "cached too, 'Up to 3 shrines may be active at a time', and it "
            "is the stock of 2 that binds below it."
        ),
        charges=2,
    )
}
parse_abilities = build_parser(
    SLOTS, "Bard", cc_kinds=MODULE_CC, charge_rules=CHARGE_RULES
)


SOURCES = load_champion_sources("Bard")

# E and R are emitted rows that price nothing, so the coverage they derive
# from SLOTS ("modeled") would overstate them.  W stays modeled: its own
# row prices no damage, but the ally-support scanner prices its sourced
# heal off the cast this slot schedules.
MODULE_COVERAGE = coverage(no_damage="ER")
