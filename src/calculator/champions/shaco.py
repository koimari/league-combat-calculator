"""Shaco — CP10.7 full-entry-reviewed packet module.

E4 summon: W (Jack in the Box) is a summoned trap.  Once sprung, the box
remains for 5 seconds and "automatically fire[s] at nearby visible
enemies every 0.5 seconds" — up to 10 attacks at the sourced cadence.
Against a single target (the fight model's duel) the box always attacks
only one enemy, so each shot uses its "Increased Damage" row
(25/40/55/70/85 + 18% AP by rank) rather than the plain Magic Damage
row.  One fully-sprung box prices ``w_box_attacks`` x Increased Damage.

- ``w_box_attacks`` (default 10) — the player-controlled uptime: 10 is
  the box's full sprung lifetime at the sourced 0.5s cadence; reduce it
  to model the target leaving the box's 450 range mid-fight.
- The sprung box fear is a typed downtime event. The same instant root and
  slow remain utility. The full-volley default assumes the box has sprung.

Boundary: box HP/stealth, arm time, trigger radius, targeting AI and
leash range are state outside the damage model.

Roadmap session 4 batch G (2026-08-21) — P (Backstab), the on-hit rider:
unlike this batch's other four label-fix reclassifications (Ryze P, Senna
E, Swain P, Tahm Kench E, all out_of_scope -> no_damage on a verified
zero-formula basis), Shaco P's pinned reviewed packet mislabels a real,
sourced formula as "no_damage." The cached P effect (data/champions.json)
reads "Shaco's basic attacks are empowered to deal 20 : 31.18 (based on
level) (+ 20% bonus AD) bonus physical damage when hitting an enemy from
behind. This damage is affected by critical strike modifiers," with a
20-value (level 1-20) "Per-Level Scaling" leveling row and
``affects: "Enemies"`` / ``damageType: "PHYSICAL_DAMAGE"``. The game file
(shaco.bin.json ``Characters/Shaco/Spells/ShacoPassiveAbility/
ShacoPassive``) corroborates the AD-ratio term exactly:
``mSpellCalculations.BasicAttackDamage`` sums a ``ByCharLevelInterpolation``
flat term with ``StatByNamedDataValue(mStat=2, mStatFormula=2,
AttackBonusADRatio=0.2)`` — 0.2 matching the wiki's "20% bonus AD" prose
1:1 (mStat 2/mStatFormula 2 is this repo's pinned bonus-AD stat code, the
same convention Senna's Q uses). The positional "from behind" condition
has no representation in this engine's stateless single-target duel model
(no facing/positioning state exists anywhere in the combatant layer), so
the bonus is priced through an explicit option (``p_backstab``, default
False — the deterministic default assumes the attacker is not positioned
behind, matching Shaco's own ``e_execute``/``r_clone_attacks`` convention
for caller-supplied state this engine cannot derive). The bonus rides
every basic-attack on-hit (per-level flat + 20% bonus AD) at the flat
per-hit amount, crit-conservative (no crit roll applied to it — the
Riven P/Runic Blade precedent, E5-2 fix): exact at 0% crit chance,
conservative above it.

P1-2 fixes:
- E (Two-Shiv Poison): the wiki's execute branch — "increased by 50% if
  they are below 30% of their maximum health" — is now selectable via
  the ``e_execute`` option (default False, a full-health target): the
  sourced "Increased Damage" row (105/142.5/180/217.5/255 by rank +
  120% bonus AD + 90% AP) replaces the base "Magic Damage" row.
- R (Hallucinate): the controllable clone is expressed as an option —
  ``r_clone_attacks`` (default 0) prices that many clone basic attacks
  (75% of Shaco's total AD physical damage each, wiki Pets prose); the
  death-explosion Magic Damage row remains the R packet's cast damage.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import ControlEvent, DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    on_hit_entry,
)

# Sourced box attack pattern (wiki Shaco W + "Champion summoned units"
# page): the sprung box fires every 0.5 seconds for its 5-second
# lifetime == 10 attacks max.
_BOX_ATTACK_INTERVAL = 0.5
_BOX_SPRUNG_SECONDS = 5.0
_BOX_MAX_ATTACKS = int(_BOX_SPRUNG_SECONDS / _BOX_ATTACK_INTERVAL)  # 10

# HARDCODED: verify on patch updates — the clone's basic attacks deal
# 75% of Shaco's total attack damage (wiki "Pets" page prose for
# Hallucination; the cached R JSON carries no leveling row for it).
_CLONE_ATTACK_AD_RATIO = 0.75

# HARDCODED: verify on patch updates — Backstab's AD ratio is sourced by
# both the wiki prose ("+ 20% bonus AD") and the game file
# (shaco.bin.json ShacoPassive.mSpell.DataValues AttackBonusADRatio =
# 0.2, consumed by mSpellCalculations.BasicAttackDamage's
# StatByNamedDataValue term, mStat=2/mStatFormula=2 = bonus AD) —
# cross-authority match on the ratio.
_BACKSTAB_BONUS_AD_RATIO = 0.20


def _backstab(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Backstab — bonus physical damage on basic attacks from behind.

    "From behind" is a positional condition this engine's stateless
    single-target duel has no facing/positioning state to derive, so the
    bonus is priced only when the caller opts in via ``p_backstab``
    (default False — the same convention as ``e_execute``/
    ``r_clone_attacks`` for state this module cannot infer). When armed,
    every basic-attack on-hit carries the sourced per-level flat term
    (level-indexed "Per-Level Scaling", not ability rank — the passive has
    no ranks) plus 20% of bonus AD, priced at the flat per-hit amount
    (crit-conservative — see module docstring; exact at 0% crit).
    """
    ability = ctx.ability()
    if ability is None:
        return None
    armed = bool(ctx.options.get("p_backstab", False))
    per_level = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    bonus_ad = float(ctx.stats.get("bonus_attack_damage", 0.0) or 0.0)
    per_hit = (per_level + _BACKSTAB_BONUS_AD_RATIO * bonus_ad) if armed else 0.0
    entry = on_hit_entry(ability.get("name", "Backstab"), per_hit, "physical")
    entry["detail"] = (
        f"{per_level:g} (level {ctx.level}) + "
        f"{_BACKSTAB_BONUS_AD_RATIO:.0%} bonus AD bonus physical damage per "
        "basic attack from behind (crit-conservative flat amount)"
        if armed
        else "p_backstab is False: attacks are not landing from behind "
        "(no bonus priced)"
    )
    return entry


_backstab.phase = ONHIT


def _jack_in_the_box(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the sprung box's single-target attack volley."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attacks = min(
        max(int(ctx.options.get("w_box_attacks", _BOX_MAX_ATTACKS)), 1),
        _BOX_MAX_ATTACKS,
    )
    per_shot = extract_named(ability, "Increased Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Jack in the Box"),
        rank,
        extract_cooldown(ability, rank),
        per_shot * attacks,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_shot,
            count=attacks,
            time_offset=0.0,
            hit_interval=_BOX_ATTACK_INTERVAL,
        ),
    )
    entry["control_events"] = (
        ControlEvent(
            "fear",
            extract_value(ability, "Fear Duration", rank),
            time_offset=0.0,
        ),
    )
    entry["event_order_certified"] = "sourced box attack cadence"
    entry["detail"] = (
        f"Box fires {attacks} shot(s) at {_BOX_ATTACK_INTERVAL:g}s intervals "
        f"(full {_BOX_SPRUNG_SECONDS:g}s sprung lifetime), each using the "
        "single-target Increased Damage row; fear/root/slow are utility."
    )
    return entry


def _two_shiv_poison(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the base Magic Damage row, or the <30%-HP execute row."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    execute = bool(ctx.options.get("e_execute", False))
    attribute = "Increased Damage" if execute else "Magic Damage"
    raw = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Two-Shiv Poison"),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", raw),)
    entry["detail"] = (
        "increased-by-50% damage against a target below 30% of its maximum "
        "health (sourced Increased Damage row)"
        if execute
        else "base Magic Damage row (target above 30% of its maximum health)"
    )
    return entry


def _hallucinate(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the death-explosion Magic Damage plus commanded clone attacks."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    explosion = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    clone_attacks = min(max(int(ctx.options.get("r_clone_attacks", 0)), 0), 30)
    ad = float(ctx.stats.get("attack_damage", 0.0))
    per_clone_hit = _CLONE_ATTACK_AD_RATIO * ad
    parts: list[DamagePart] = [DamagePart("magic", explosion)]
    if clone_attacks > 0:
        parts.append(
            DamagePart(
                "physical",
                per_clone_hit,
                count=clone_attacks,
                time_offset=0.0,
                hit_interval=1.0 / max(0.1, float(ctx.stats.get("attack_speed", 1.0))),
            )
        )
    entry = damage_entry(
        ability.get("name", "Hallucinate"),
        rank,
        extract_cooldown(ability, rank),
        explosion + per_clone_hit * clone_attacks,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"clone death-explosion ({explosion:g} magic) plus "
        f"{clone_attacks} commanded clone basic attack(s) at "
        f"{_CLONE_ATTACK_AD_RATIO:.0%} AD ({per_clone_hit:g} physical each); "
        "the clone is a controllable summon, so its attack count is the "
        "r_clone_attacks option"
    )
    return entry


PACKET_SHA256 = "3a7a57f56c3c5d06404558fb69b2bdac0244775181a3b338c6cf369b8f328ffa"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Shaco", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["P"] = _backstab
SLOTS["W"] = _jack_in_the_box
SLOTS["E"] = _two_shiv_poison
SLOTS["R"] = _hallucinate
parse_abilities = build_parser(SLOTS, "Shaco")
ASSUMPTIONS.extend(
    [
        "P (Backstab) rides every basic-attack on-hit with a sourced "
        "level-indexed flat term plus 20% bonus AD, but only when "
        "p_backstab=True (default False, an attacker not positioned "
        "behind the target); the engine has no facing/positioning state "
        "to derive this on its own. Priced at the flat per-hit amount "
        "(crit-conservative, no crit roll applied — exact at 0% crit "
        "chance, conservative above it).",
        "W (Jack in the Box) is a summoned trap: the sprung box fires "
        "every 0.5s for its 5-second lifetime (10 shots max); "
        "w_box_attacks is the player-controlled uptime and defaults to "
        "the full sourced volley.",
        "The fight model is a single-target duel, so the box always uses "
        "its Increased Damage row (attacks only one target), never the "
        "plain Magic Damage row.",
        "The sprung box applies its sourced fear at the first volley hit; "
        "the same instant root and slow remain utility. Box HP, arm time, "
        "trigger radius and leash range are state outside the model.",
        "E (Two-Shiv Poison) prices the base Magic Damage row by default "
        "(the deterministic target is above 30% of its maximum health); "
        "e_execute=True prices the sourced Increased Damage row for "
        "targets below 30% max health (105/142.5/180/217.5/255 + 120% "
        "bonus AD + 90% AP by rank).",
        "R (Hallucinate) prices the clone death-explosion Magic Damage; "
        "the controllable clone's basic attacks are r_clone_attacks "
        "(default 0 = the player does not command the clone to attack), "
        "each dealing 75% of Shaco's total AD physical damage (wiki Pets "
        "prose, module constant).",
    ]
)
OPTIONS.append(
    {
        "key": "p_backstab",
        "type": "bool",
        "default": False,
        "label": "P Backstab: basic attacks land from behind (bonus "
        "physical damage)",
    }
)
OPTIONS.append(
    {
        "key": "w_box_attacks",
        "type": "int",
        "default": _BOX_MAX_ATTACKS,
        "min": 1,
        "max": _BOX_MAX_ATTACKS,
        "label": "Jack in the Box attacks",
    }
)
OPTIONS.append(
    {
        "key": "e_execute",
        "type": "bool",
        "default": False,
        "label": "E hits a target below 30% max HP (increased damage)",
    }
)
OPTIONS.append(
    {
        "key": "r_clone_attacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 30,
        "label": "R clone basic attacks commanded",
    }
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
