"""Ivern's brush on-hit, Triggerseed explosion and Daisy summon damage."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    simple_damage,
    with_control,
)
from .source_receipts import load_champion_sources


def _brushmaker(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    if not bool(ctx.options.get("w_in_brush", True)):
        return no_damage(
            ctx,
            name=ability.get("name", "Brushmaker"),
            reason="Brushmaker is active utility while not in brush.",
            slot="W",
        )
    value = extract_named(
        ability, "Additional Magic Damage", ctx.rank_for(), ctx.stats, ctx.target
    )
    entry = on_hit_entry(ability.get("name", "Brushmaker"), value, "magic")
    entry["detail"] = (
        "Brushmaker bonus attack magic damage; brush duration and allied-brush branch are explicit state."
    )
    return entry


_brushmaker.phase = ONHIT


def _triggerseed(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Triggerseed"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=2.0),)
    entry["detail"] = (
        "Shield is granted immediately; the sourced explosion occurs after two seconds."
    )
    return entry


# HARDCODED: verify on patch updates — Daisy's attack stats are not in the
# champion JSON (the R text says only "See Pets for more details").  Sourced
# from the Community Dragon game files (current patch) and the wiki pet
# infobox:
#   https://raw.communitydragon.org/latest/game/data/characters/
#     ivern/ivern.bin.json (IvernR DataValues: DaisyAD, DaisyAS,
#       ShockwaveBaseDamage) and ivernminion/ivernminion.bin.json (unit AS
#       0.75 base)
#   https://wiki.leagueoflegends.com/en-us/Ivern (Daisy pet section)
# Daisy basic attack: 70/100/130 (R rank 1/2/3) (+ 15% AP) physical at
# 0.75 (+ 30/45/60% based on R rank) attack speed -> 1.2 at R rank 3, so
# the default 6 attacks fill the 5-second one-rotation window.
# Daisy Smash!: every third basic attack is empowered (after 2 stacks) to
# deal 90/140/190 (R rank) (+ 50% AP) magic damage and knock up — priced
# as the sourced magic part below; the 3s post-smash lockout is state.
_DAISY_AD_BY_RANK = (70.0, 100.0, 130.0)
_DAISY_AD_AP_RATIO = 0.15
_DAISY_AS_BONUS_BY_RANK = (0.30, 0.45, 0.60)
_DAISY_BASE_AS = 0.75
_DAISY_SMASH_BY_RANK = (90.0, 140.0, 190.0)
_DAISY_SMASH_AP_RATIO = 0.50


def _daisy(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Daisy! — basic attacks plus the 3-hit Daisy Smash knockup."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attacks = min(max(int(ctx.option("daisy_attacks")), 0), 20)
    if attacks <= 0:
        return no_damage(
            ctx,
            name="Daisy!",
            reason="daisy_attacks is 0 — set it to price Daisy's attacks.",
        )
    index = min(rank - 1, len(_DAISY_AD_BY_RANK) - 1)
    ap = ctx.stat("ability_power")
    per_attack = _DAISY_AD_BY_RANK[index] + _DAISY_AD_AP_RATIO * ap
    per_smash = _DAISY_SMASH_BY_RANK[index] + _DAISY_SMASH_AP_RATIO * ap

    # Every third attack is the empowered Daisy Smash (the smash replaces
    # the ordinary swing, so the counts never double-price an attack).
    smashes = attacks // 3
    normals = attacks - smashes
    interval = 1.0 / (_DAISY_BASE_AS * (1.0 + _DAISY_AS_BONUS_BY_RANK[index]))
    entry = damage_entry(
        ability.get("name", "Daisy!"),
        rank,
        extract_cooldown(ability, rank),
        per_attack * normals + per_smash * smashes,
        "physical",
    )
    # Daisy's ordinary swings apply nothing; the smash this module already
    # reviews as a knockup carries that kind, which is why R's kinds ride
    # its parts instead of MODULE_CC.
    entry["parts"] = (
        DamagePart(
            "physical",
            per_attack,
            count=normals,
            time_offset=0.0,
            hit_interval=interval,
            cc_kind="none",
        ),
        DamagePart(
            "magic",
            per_smash,
            count=smashes,
            time_offset=2.0 * interval,
            hit_interval=3.0 * interval,
            cc_kind="knockup",
        ),
    )
    entry["detail"] = (
        f"Daisy: {attacks} attacks ({normals} basic of {per_attack:.2f} physical "
        f"+ {smashes} Daisy Smash of {per_smash:.2f} magic) at "
        f"{_DAISY_BASE_AS * (1.0 + _DAISY_AS_BONUS_BY_RANK[index]):.2f} attack "
        "speed; the 3s smash lockout and knockup CC are state"
    )
    return entry


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Friend of the Forest",
        reason="Grove channel, health/mana cost, camp release and full bounty are jungle utility state.",
    ),
    # The vine damages "the first enemy hit and root[s] them"; the root's
    # duration is read off the packet's own Root Duration row rather than
    # restated, and the single-hit certification is what carries the kind
    # into the event ledger.
    "Q": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        kind="root",
        duration_attr="Root Duration",
    ),
    "W": _brushmaker,
    "E": _triggerseed,
    "R": _daisy,
}

# Q's vine damages "the first enemy hit and root[s] them"; E's seed
# "explode[s] to deal magic damage to nearby enemies and slow them for 2
# seconds".  R is absent because Daisy's two packets differ (see _daisy).
# P and W author no damage part (W is the on-hit bolt).
MODULE_CC = {"Q": "root", "E": "slow"}

parse_abilities = build_parser(SLOTS, "Ivern", cc_kinds=MODULE_CC)
OPTIONS = [
    {
        "key": "w_in_brush",
        "type": "bool",
        "default": True,
        "label": "Ivern is in brush",
    },
    {
        "key": "daisy_attacks",
        "type": "int",
        "default": 6,
        "label": "Daisy attacks (5s window)",
        "min": 0,
        "max": 20,
    },
]
ASSUMPTIONS = [
    "Ivern's non-epic monster prohibition and grove economics are preserved as utility/state.",
    "Brushmaker's self bonus attack is an on-hit package; allied champion bolts are a separate roster branch.",
    "Daisy's basic attacks (70/100/130 by R rank + 15% AP physical) and the "
    "third-hit Daisy Smash (90/140/190 by R rank + 50% AP magic) are "
    "game-file constants; verify on patch updates against Community Dragon",
    "Daisy attacks at 0.75 (+ 30/45/60% by R rank) attack speed; the default "
    "6 attacks fill the 5-second one-rotation window and the sourced 3-hit "
    "smash cadence prices one smash per 3 attacks (the smash replaces the "
    "ordinary swing)",
    "Daisy Smash!'s 3-second lockout, knockup/stun CC, spawn damage "
    "reduction and leash range are state, not modeled",
    "E (Triggerseed) shields the target allied champion, Daisy, or Ivern "
    "himself (cached prose 'or himself', so the scanner profile is "
    "self-or-target one_teammate): the roster model shields the selected "
    "teammate for the sourced Shield Strength (75-235 + 50% AP) for 2s "
    "and falls back to Ivern in a solo fight; the sourced explosion "
    "damage after 2s and the slow are the module's E damage entry.",
]
SOURCES = load_champion_sources("Ivern")
