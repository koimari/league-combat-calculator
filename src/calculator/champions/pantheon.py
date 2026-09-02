"""Pantheon — CP10.6 full-entry-reviewed packet module (E9-2 gap fixes).

The CP-era gap items are closed here:
- Q (Comet Spear) prices the Hurl base (70-190 + 115% bonus AD + 50% AP)
  plus the Mortal Will empowered term (20 : 265.88 by level + 115%
  bonus AD; Pantheon starts fights with maximum stacks, so the first
  basic ability is empowered by default).  The <20%-HP execute — the
  Increased Hurl Damage row (155-455 + 230% bonus AD + 100% AP) — is
  exposed through the ``q_execute`` option (the user states the target
  is below the threshold when Q lands).
- W (Shield Vault) prices its sourced %max-HP physical damage row
  (6-8% + 1.5% per 100 AP + 0.4% per 100 bonus health of the target's
  maximum health) instead of reading the percentage as flat damage —
  MODULE_COVERAGE flips W to modeled.
- R (Grand Starfall) prices the center Magic Damage row by default and
  exposes the Reduced edge row (150-350 + 50% AP) through the ``r_edge``
  option.
- P (Mortal Will) is a ``no_damage`` row, not a missing axis: the
  empowered rider is priced in Q, and what remains is the resource
  stack counter, which grants nothing the engine would price.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import (
    calculation_coefficient,
    calculation_stat_coefficient,
    data_value,
    spell_object,
)
from .engine import SlotCtx
from .inputs import bool_option, float_option
from .module_contract import coverage
from .module_helpers import ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

PACKET_SHA256 = "604839aed7fc6d6741cf14f1a8d6d58554dce93cd8c14bea5ac73d82215e771a"


# The cached prose identifies these terms; the binary owns their numeric
# coefficients. The W coefficient is stored as a fraction per health point,
# while the module's public unit is percentage points per 100 bonus health.
_PANTHEON_Q_SPELL = spell_object("Pantheon", "PantheonQ")
_PANTHEON_W_SPELL = spell_object("Pantheon", "PantheonW")
_MORTAL_WILL_BONUS_AD_RATIO = calculation_coefficient(
    _PANTHEON_Q_SPELL, "EmpoweredDamageCalc"
)
_W_BONUS_HEALTH_PER_100 = (
    calculation_stat_coefficient(_PANTHEON_W_SPELL, "MaxHealthDamageCalc", 12) * 10000.0
)
_W_STUN_SECONDS = data_value(_PANTHEON_W_SPELL, "StunDuration")


@ranked_slot
def _comet_spear(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: Hurl base (or <20%-HP execute) + the Mortal Will empowered term."""

    if bool(ctx.option("q_execute")):
        # Target below 20% of maximum health: the Increased Hurl Damage row.
        base = extract_named(
            ability, "Increased Hurl Damage", rank, ctx.stats, ctx.target
        )
        branch = "execute"
    else:
        base = extract_named(
            ability, "Hurl Physical Damage", rank, ctx.stats, ctx.target
        )
        branch = "hurl"

    empowered = 0.0
    if bool(ctx.option("q_mortal_will")):
        per_level = extract_value(ability, "Per-Level Scaling", ctx.level)
        empowered = per_level + _MORTAL_WILL_BONUS_AD_RATIO * float(
            ctx.stat("bonus_attack_damage") or 0.0
        )

    value = base + empowered
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value),)
    # One spear, hurled or thrust, on the enemies in its line — one part
    # and one hit, which carries Q's reviewed control answer into the
    # event ledger.
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"{branch} row + Mortal Will empowered term "
        f"({per_level if empowered else 0.0:g} by level + 115% bonus AD)"
    )
    return entry


@ranked_slot
def _shield_vault(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: %max-HP physical damage with the AP and bonus-health per-100 terms."""

    target_max = float(ctx.target_stat("target_max_health") or 0.0)
    ap = float(ctx.stat("ability_power") or 0.0)
    bonus_health = float(ctx.stat("bonus_health") or 0.0)
    percent = extract_value(ability, "Physical Damage", rank, 0)
    percent += extract_value(ability, "Physical Damage", rank, 1) * ap / 100.0
    percent += _W_BONUS_HEALTH_PER_100 * bonus_health / 100.0
    value = percent / 100.0 * target_max

    # The stun itself is declared once in MODULE_CC; certifying the event
    # order is the separate claim that gets the marker into the ledger —
    # a marker outside the ledger never triggers Imperial Mandate's
    # Command or Fimbulwinter's Everlasting.
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
        event_order_certified="single_hit",
    )
    # HARDCODED: verify on patch updates — the cached W description states
    # the interval in prose ("stuns them for 1 second"), with no leveling
    # row to read it from.  The kind it belongs to is MODULE_CC's, stamped
    # after every phase onto the part this line rebuilds.
    entry["parts"] = (DamagePart("physical", value, cc_duration=_W_STUN_SECONDS),)
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"%max-HP physical damage row: {percent:g}% of the target's "
        "maximum health (1.5% per 100 AP + 0.4% per 100 bonus health)."
    )
    return entry


@ranked_slot
def _grand_starfall(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: center Magic Damage row, or the Reduced edge row when selected."""

    attr = "Reduced Damage" if bool(ctx.option("r_edge")) else "Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    # One shockwave crossing the target area — one part and one hit, which
    # carries R's reviewed slow into the event ledger.
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"{'Reduced edge' if attr == 'Reduced Damage' else 'Center'} "
        "Magic Damage row (edge hits take up to 50% less)."
    )
    return entry


# Reviewed crowd control, read from the cached kit.  Q (Comet Spear)
# "deals physical damage to enemies hit": the only slow in its text is on
# Pantheon himself while he "charges while being slowed by 10%".  W
# (Shield Vault) "deals physical damage and stuns them for 1 second".  E
# (Aegis Assault) braces, strikes and slams with no control clause.  R
# (Grand Starfall) "deals ... physical damage to enemies near the impact
# and slows them by 50% for 2 seconds" — the row prices the shockwave of
# that same cast, which lands on the target the spear slowed.  P authors
# no damage part.
MODULE_CC = {"W": "stun", "Q": "none", "E": "none", "R": "slow", "P": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Pantheon",
    PACKET_SHA256,
    # The row this packet prices for E is the recast slam ("Recast:
    # Pantheon slams with his shield in a cone in front of him,
    # dealing physical damage to enemies hit") — one part and one
    # hit; the channel's 0.125-second strikes stay unpriced.
    single_hit_slots=frozenset({"E"}),
    slot_parsers={
        "Q": _comet_spear,
        "W": _shield_vault,
        "R": _grand_starfall,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS: list[dict[str, Any]] = [
    *list(OPTIONS),
    bool_option(
        "q_execute",
        False,
        label="Q hits a target below 20% maximum health (execute row)",
    ),
    bool_option(
        "q_mortal_will",
        True,
        label="Mortal Will empowered Q (first basic ability at 5 stacks)",
    ),
    bool_option("r_edge", False, label="R edge hit (Reduced Damage row)"),
    bool_option(
        "e_active", False, label="E (Aegis Assault) active against selected skillshots"
    ),
    float_option(
        "e_active_from",
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="E active start time in seconds",
    ),
    float_option(
        "e_active_seconds",
        0.0,
        minimum=0.0,
        maximum=1.5,
        label="E active seconds; zero uses the sourced 1.5 second duration",
    ),
    {
        "key": "e_blocked_skillshots",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Front-facing skillshot slots to block; an empty list blocks all marked "
            "skillshots"
        ),
    },
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q prices the Hurl Physical Damage row plus the Mortal Will empowered "
    "term (20 : 265.88 by level + 115% bonus AD) — Pantheon starts fights "
    "with maximum Mortal Will stacks (cached P description), so the first "
    "basic ability is empowered by default (q_mortal_will, toggleable)",
    "Q's <20%-HP execute is the Increased Hurl Damage row (155-455 + 230% "
    "bonus AD + 100% AP), exposed through the q_execute option — the "
    "target's HP threshold is player state, not a fight-engine boundary",
    "W (Shield Vault) deals %max-HP physical damage (6-8% by rank + 1.5% "
    "per 100 AP + 0.4% per 100 bonus health of the target's maximum "
    "health); the AP and bonus-health per-100 terms are the cached "
    "modifiers with the garbled '% per 100 Pantheon's bonus health' unit "
    "pinned as '% per 100 bonus health'. The champion hit stuns for one "
    "second, from the cached ability description",
    "R prices the center Magic Damage row by default; the Reduced edge "
    "row (150-350 + 50% AP) is exposed through the r_edge option.  The R "
    "passive armor penetration (10-30% by rank) is a self-stat, not "
    "enemy damage.",
    "E Aegis Assault blocks selected marked skillshots during the sourced "
    "1.5 second front-facing channel; direction is represented by the "
    "explicit source selection.",
    "P (Mortal Will) itself has no enemy-damage formula in the pinned "
    "packet; it emits the sourced zero-damage row (MODULE_COVERAGE: "
    "no_damage, not out_of_scope). P is already a cast slot in this "
    "module (never overridden from build_packet_module's no_damage "
    "branch); its empowered rider is priced in Q, not on P itself.",
]

# P emits a row and there is nothing left for it to price — Mortal Will's
# only damage is the empowered rider, which Q prices — so it is no_damage,
# not a missing axis.  The bare stack counter is resource state.
MODULE_COVERAGE = coverage(no_damage="P")
