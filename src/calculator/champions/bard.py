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
- W (Caretaker's Shrine) is an ally-only heal/MS buff — its "Minimum
  Heal"/"Maximum Heal" attributes are NOT damage; absent from the map.
  E8d: the engine's ally-support scanner looks up ("Total Heal", "Heal",
  "Heal Per Tick") only, so Bard's "Minimum Heal"/"Maximum Heal" rows are
  not readable by the support path — the W ally heal is a documented missing
  engine hook (support_effects heal-attribute lookup), not an emitted packet.
- E (Magical Journey) is a one-way terrain portal, zero damage — absent.
- R (Tempered Fate) is 2.5s stasis, zero damage (stasis prevents damage
  during it) — absent; no zero-damage display row wanted.
"""

from typing import Any

from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import ability_on_hit_entry, simple_damage, with_control

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
        self.source = {
            "label": "Local League Wiki cache — Bard P (Traveler's Call) prose",
            "url": "https://wiki.leagueoflegends.com/en-us/Bard",
            "revision_id": 4002472,
            "revision_timestamp": "2026-03-25T15:16:50Z",
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
    ap = ctx.stats.get("ability_power", 0.0)
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
    "W (heal), E (portal), and R (stasis) deal no damage and are "
    "excluded from the breakdown",
]

SLOTS = {
    "P": _travelers_call,
    "Q": with_control(
        simple_damage(attr="Magic Damage", dmg_type="magic"),
        kind="stun",
        duration_attr="Disable Duration",
    ),
}

parse_abilities = build_parser(SLOTS, "Bard")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Bard",
        "revision_id": 4002472,
        "revision_timestamp": "2026-03-25T15:16:50Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
