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
- P (Mortal Will) remains a documented no-damage row; the empowered
  rider on Q is priced in Q, not P.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_06 import build_batch_module
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_batch_module("Pantheon")
)

# HARDCODED: verify on patch updates — wiki prose on Q: the Mortal Will
# empowered term is "20 : 265.88 (based on level) (+ 115% bonus AD)"; the
# per-level flat is the cached Per-Level Scaling row, the AD ratio is
# prose.  W's "% per 100 Pantheon's bonus health" is a garbled variant of
# "% per 100 bonus health" (0.4 at every rank).
_MORTAL_WILL_BONUS_AD_RATIO = 1.15
_W_BONUS_HEALTH_PER_100 = 0.4


def _comet_spear(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Hurl base (or <20%-HP execute) + the Mortal Will empowered term."""
    ability = ctx.ability("Q", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None

    if bool(ctx.options.get("q_execute", False)):
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
    if bool(ctx.options.get("q_mortal_will", True)):
        per_level = extract_value(ability, "Per-Level Scaling", ctx.level)
        empowered = per_level + _MORTAL_WILL_BONUS_AD_RATIO * float(
            ctx.stats.get("bonus_attack_damage", 0.0) or 0.0
        )

    value = base + empowered
    entry = damage_entry(
        ability.get("name", "Comet Spear"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value),)
    entry["detail"] = (
        f"{branch} row + Mortal Will empowered term "
        f"({per_level if empowered else 0.0:g} by level + 115% bonus AD)"
    )
    return entry


def _shield_vault(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: %max-HP physical damage with the AP and bonus-health per-100 terms."""
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    target_max = float(ctx.target.get("target_max_health", 0.0) or 0.0)
    ap = float(ctx.stats.get("ability_power", 0.0) or 0.0)
    bonus_health = float(ctx.stats.get("bonus_health", 0.0) or 0.0)
    percent = extract_value(ability, "Physical Damage", rank, 0)
    percent += extract_value(ability, "Physical Damage", rank, 1) * ap / 100.0
    percent += _W_BONUS_HEALTH_PER_100 * bonus_health / 100.0
    value = percent / 100.0 * target_max

    entry = damage_entry(
        ability.get("name", "Shield Vault"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, cc_kind="stun"),)
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"%max-HP physical damage row: {percent:g}% of the target's "
        "maximum health (1.5% per 100 AP + 0.4% per 100 bonus health)."
    )
    return entry


def _grand_starfall(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: center Magic Damage row, or the Reduced edge row when selected."""
    ability = ctx.ability("R", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None

    attr = (
        "Reduced Damage" if bool(ctx.options.get("r_edge", False)) else "Magic Damage"
    )
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Grand Starfall"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["detail"] = (
        f"{'Reduced edge' if attr == 'Reduced Damage' else 'Center'} "
        "Magic Damage row (edge hits take up to 50% less)."
    )
    return entry


SLOTS = dict(_packet_slots)
SLOTS["Q"] = _comet_spear
SLOTS["W"] = _shield_vault
SLOTS["R"] = _grand_starfall
parse_abilities = build_parser(SLOTS, "Pantheon")

OPTIONS: list[dict[str, Any]] = list(_packet_options) + [
    {
        "key": "q_execute",
        "type": "bool",
        "default": False,
        "label": "Q hits a target below 20% maximum health (execute row)",
    },
    {
        "key": "q_mortal_will",
        "type": "bool",
        "default": True,
        "label": "Mortal Will empowered Q (first basic ability at 5 stacks)",
    },
    {
        "key": "r_edge",
        "type": "bool",
        "default": False,
        "label": "R edge hit (Reduced Damage row)",
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
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
    "pinned as '% per 100 bonus health'",
    "R prices the center Magic Damage row by default; the Reduced edge "
    "row (150-350 + 50% AP) is exposed through the r_edge option.  The R "
    "passive armor penetration (10-30% by rank) is a self-stat, not "
    "enemy damage.",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    "P": "out_of_scope",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"
