"""Kindred — Mark of the Kindred and Mounting Dread (3-stack) systems.

Stack mechanics modeled (E3):
- P (Mark of the Kindred): takedowns on hunted targets collect Marks.
  Marks grant 75 : 250 (based on marks) bonus basic-attack range,
  +5% attack speed per mark on Q, and scale E's missing-health term
  (+0.5% per mark).  ``marks`` is the explicit pre-stack state.
- E (Mounting Dread): the active shot marks the target; basic attacks
  against the marked target apply stacks (cap 3).  The third stack
  directs Wolf to pounce, consuming all stacks to deal the sourced
  "Additional Physical Damage" (80 : 200 by rank + 100% bonus AD + 5%
  (+ 0.5% per Mark) of the target's missing health), increased by up to
  50% based on critical strike chance (wiki prose).  ``e_stacks`` is
  the explicit pre-stack state; the pounce is priced at 3 stacks.

Q (Dance of Arrows) and R (Lamb's Respite) keep the reviewed CP10.3
packet pricing.  W (Wolf's Frenzy) is the E4 summon row: Wolf's frenzy
attacks price the sourced "Magic Damage" leveling with the full
per-Mark current-health term (+1% per Mark, resolved via the same
modifier override Mounting Dread uses), over ``w_attacks`` attacks
(Wolf attacks at 25% of Kindred's bonus attack speed; the count is the
player-controlled option, default 3 attacks in the window).

Coverage (roadmap session 4, 2026-08-20): every stale ``out_of_scope``
label closes, with no behavior change -- ``MODULE_COVERAGE`` was simply
stale for slots the CP10.3 packet review had already closed, the identical
stale-label pattern Alistar-P/Anivia-P were corrected under in the prior
roadmap session.  P (Mark of the Kindred) and R (Lamb's Respite) each emit
an explicit ``no_damage`` row: P's marks are the range/attack-speed/scaling
state the other slots already read, and R's minimum-health zone is state
(its end heal is paid by ``derive_self_healing`` below -- the ally scanner
pays every teammate in the zone and the caster's own copy -- not as enemy
damage).  Q, W and E each price their own row.

  - Q (Dance of Arrows): the atoms capture (data/atoms/kindred.atoms.json,
    behavior KindredQ) and the cached leveling both carry a real
    "Physical Damage" row; ``_dance_of_arrows`` already prices it via
    ``typed_damage``. Simple mislabel fix.
  - R (Lamb's Respite): the atoms capture's KindredR rows are
    ``damage.aoe`` with ``damage_type: null`` (a structural AoE-zone tag,
    not a priced formula -- the "minimum-health, can't die" zone), plus a
    self-only ``heal-shield.heal`` (already paid by
    ``derive_self_healing`` below) and a self buff. No enemy-damage
    number exists to price; the no-death zone stays state, matching the
    Kai'Sa-R precedent for a sourced-but-structurally-non-damage rider.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .inputs import champion_stat, int_option
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .module_helpers import no_damage, typed_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)
from .source_receipts import load_champion_sources
from .. import healing_helpers as _healing
from .module_contract import coverage


def _dance_of_arrows(ctx: SlotCtx) -> dict[str, Any] | None:
    result = typed_damage(ctx, "Physical Damage", "physical")
    if result:
        # One arrow per nearby enemy, fired at the cast: the boundary claim
        # that carries MODULE_CC's answer for Q into the event ledger.
        result["event_order_certified"] = "single_hit"
        result["detail"] = (
            f"Dance of Arrows; {int(ctx.option('marks'))} Mark of "
            "the Kindred stacks grant the sourced attack-speed state."
        )
    return result


_BASE_SLOTS = {
    "Q": _dance_of_arrows,
    "R": lambda ctx: no_damage(
        ctx,
        name="Lamb's Respite",
        reason=(
            "The minimum-health zone and end heal are defensive/utility "
            "state, not enemy damage."
        ),
    ),
}
_MARK_MAX = 25
_E_STACK_MAX = 3

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Mounting Dread's third-stack pounce "increased by 0% : 50% (+ 0% :
# 15%) (based on critical strike chance)" (the Akshan-R / Caitlyn-R
# crit_effectiveness precedent).
_E_POUNCE_CRIT_EFFECTIVENESS = 0.5


def _marks(ctx: SlotCtx) -> int:
    return min(max(int(ctx.option("marks")), 0), _MARK_MAX)


def _mark_of_the_kindred(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Mark state row (bonus range, Q AS, E missing-health scaling)."""
    ability = ctx.ability()
    if ability is None:
        return None
    marks = _marks(ctx)
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"{marks} Mark(s) of the Kindred: 75 : 250 (based on marks) "
            "bonus basic-attack range, +5% attack speed per mark on Q, "
            "and +0.5% per mark on E's missing-health term are state/"
            "scaling; the hunt target selection is state."
        ),
    )


def _mounting_dread(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Mounting Dread — third-stack Wolf pounce."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    stacks = min(max(int(ctx.option("e_stacks")), 1), _E_STACK_MAX)
    if stacks < _E_STACK_MAX:
        return no_damage(
            ctx,
            name=ability_name(ability),
            reason=(
                f"{stacks}/3 Mounting Dread stacks on the marked target; "
                "the third stack directs Wolf to pounce (consuming all "
                "stacks) — set e_stacks to 3 to price the pounce."
            ),
        )

    marks = _marks(ctx)
    leveling = find_named_leveling(ability, "Additional Physical Damage")
    if leveling is None:
        return None

    def per_mark_override(unit: str, value: float) -> float | None:
        """Kindred E's missing-health modifier: 5% (+ 0.5% per Mark)."""
        if "of target's missing health" not in unit:
            return None
        percent = value + 0.5 * marks
        missing = float(ctx.target_stat("target_missing_health") or 0.0)
        return percent / 100.0 * missing

    damage = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=per_mark_override
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            damage,
            crit_effectiveness=_E_POUNCE_CRIT_EFFECTIVENESS,
        ),
    )
    entry["target_max_health_sensitive"] = True
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"Third-stack Wolf pounce at {stacks}/3 stacks: {damage:.2f} "
        "physical (80 : 200 by rank + 100% bonus AD + 5% (+0.5% per "
        f"Mark) of missing health at {marks} mark(s)); the pounce "
        "consumes all stacks."
    )
    return entry


def _hunters_vigor(ctx: SlotCtx) -> dict[str, Any] | None:
    """W passive: Hunter's Vigor — the at-100-stacks next-auto heal.

    Cached W prose: "Lamb generates ... 5 stacks on-attack, up to a
    maximum of 100 stacks. At maximum stacks, her next basic attack
    heals her for 0% : 100% (based on Kindred's missing health) of
    47 : 81 (based on level)."  The module emits the receipt only when
    the ``w_hunters_vigor_stacks`` option reaches the sourced 100-stack
    cap; healing.py pays the missing-health-scaled heal on the first
    basic-attack damage event (the deterministic next auto).
    """
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    stacks = min(max(int(ctx.option("w_hunters_vigor_stacks")), 0), 100)
    if stacks < 100:
        return no_damage(
            ctx,
            slot="W",
            name="Hunter's Vigor",
            reason=(
                f"{stacks}/100 Hunter's Vigor stacks; at 100 stacks the "
                "next basic attack heals Kindred for 0% : 100% (based on "
                "missing health) of 47 : 81 (based on level)."
            ),
        )
    heal = extract_named(ability, "Heal", ctx.level, ctx.stats, ctx.target)
    return no_damage(
        ctx,
        slot="W",
        name="Hunter's Vigor",
        reason=(
            f"{stacks}/100 Hunter's Vigor stacks: the next basic attack "
            f"heals Kindred for the missing-health share of {heal:g} "
            "(47 : 81 based on level); the heal is not triggered at full "
            "health."
        ),
    )


def _wolfs_frenzy(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Wolf's Frenzy — Wolf basic attacks over the fight window.

    Wolf's attacks are magic and the rate scales with 25% of Kindred's
    bonus attack speed (wiki prose); the zone lasts 8.5 seconds.  The
    attack COUNT is the player-controlled ``w_attacks`` option (default
    3).  The per-Mark current-health term (1.5% + 1% per Mark) resolves
    through the same modifier override Mounting Dread uses, so the
    sourced formula prices exactly.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    attacks = min(max(int(ctx.option("w_attacks")), 1), 8)
    marks = _marks(ctx)
    leveling = find_named_leveling(ability, "Magic Damage")
    if leveling is None:
        return None

    def per_mark_override(unit: str, value: float) -> float | None:
        """Wolf's current-health modifier: 1.5% (+ 1% per Mark)."""
        if "of target's current health" not in unit:
            return None
        percent = value + 1.0 * marks
        current = float(ctx.target_stat("target_current_health") or 0.0)
        return percent / 100.0 * current

    per = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=per_mark_override
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        0.0,
        per * attacks,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per, count=attacks, time_offset=0.5, hit_interval=1.0),
    )
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"Wolf attacks {attacks} time(s) for {per:.2f} magic each (25 : 45 by "
        f"rank + 20% bonus AD + 20% AP + 1.5% (+1% per Mark) of current health "
        f"at {marks} mark(s)); Wolf attack speed scales with 25% of Kindred's "
        "bonus attack speed and the 8.5s zone duration are state"
    )
    return entry


SLOTS = {
    "P": _mark_of_the_kindred,
    "Q": _BASE_SLOTS["Q"],
    "W": _wolfs_frenzy,
    "W_vigor": _hunters_vigor,
    "E": _mounting_dread,
    "R": _BASE_SLOTS["R"],
}

# Cached kit review: E's active "slows them by 30% (+ 5% per 100 AP) for 1
# second" on the target its pounce then damages; Q's arrows apply no
# control, and Wolf's frenzy attacks slow only "against monsters", never
# the champion this pair fight damages.  P, W_vigor and R deal no damage.
MODULE_CC = {"Q": "none", "W": "none", "E": "slow"}

parse_abilities = build_parser(SLOTS, "Kindred", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option("marks", 0, minimum=0, maximum=25, label="Mark of the Kindred stacks"),
    int_option("w_attacks", 3, minimum=1, maximum=8, label="Wolf attacks (W)"),
    int_option(
        "w_hunters_vigor_stacks",
        100,
        minimum=0,
        maximum=100,
        label="Hunter's Vigor stacks (100 = the next basic attack heals)",
    ),
    int_option(
        "e_stacks", 3, minimum=1, maximum=3, label="Mounting Dread stacks (3 = pounce)"
    ),
]

ASSUMPTIONS = [
    "Mark of the Kindred stacks (0-25) grant bonus range (75 : 250), Q "
    "attack speed (+5% per mark) and E missing-health scaling (+0.5% per "
    "mark); takedown collection is state",
    "Mounting Dread marks for 4 seconds and stacks on basic attacks (cap "
    "3); the third stack fires the Wolf pounce, consuming all stacks — "
    "e_stacks is the explicit pre-stack state (3 prices the pounce)",
    "The pounce is the sourced Additional Physical Damage (+ 100% bonus "
    "AD + missing-health term), amplified up to 50% by critical strike "
    "chance (crit_effectiveness 0.5, wiki prose)",
    "W (Wolf's Frenzy) prices the sourced Magic Damage leveling over "
    "w_attacks Wolf attacks, including the per-Mark current-health term "
    "(1.5% + 1% per Mark); the zone duration and 25%-of-bonus-AS rate are "
    "state (attack count is the player-controlled option)",
    "W passive Hunter's Vigor: at 100 stacks (w_hunters_vigor_stacks, "
    "default 100) the next basic attack heals Kindred for the "
    "missing-health share of the sourced 47 : 81 (based on level) heal "
    "(healing.py; the heal is not triggered at full health)",
    "R (Lamb's Respite) is the reviewed no-damage packet: the minimum-"
    "health zone and end heal are defensive/utility state, not enemy "
    "damage (roadmap session 4: reclassified from out_of_scope to "
    "no_damage, no behavior change)",
    "Q (Dance of Arrows) is the reviewed physical-damage packet (roadmap "
    "session 4: reclassified from out_of_scope to modeled, no behavior "
    "change -- the slot always priced real damage)",
]

SOURCES = load_champion_sources("Kindred")
MODULE_COVERAGE = coverage(no_damage="PR")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Kindred self-healing events from its authored packet."""
    healing = []
    r = _healing.ability_json(champion_data, "R")
    r_rank = _healing.parsed_rank(ability_damages, "R")
    r_heal = _healing.extract_named(r, "Heal", r_rank, champion_stats)
    duration = max(0.0, float(fight_duration_seconds or 0.0))
    for cast_time in _healing.cast_slot_times(cast_timeline, "R"):
        heal_time = cast_time + 4.0
        if heal_time > duration + 1e-9:
            continue
        healing.append(
            {
                "time": heal_time,
                "amount": r_heal,
                "source": "Lamb's Respite",
                "kind": "champion_ability",
                "actor_wide": True,
            }
        )
    # W passive Hunter's Vigor: at 100 stacks the next basic attack
    # heals Kindred for 0% : 100% (based on her missing health) of the
    # sourced per-level heal (47 : 81, data/champions.json W "Heal"
    # per-level row).  The module emits the W_vigor receipt only at
    # 100 stacks; the heal pays on the first basic-attack damage event
    # (the deterministic next auto) and is naturally zero at full
    # health (the wiki says it is not triggered there).
    if "W_vigor" in ability_damages:
        level = int(champion_stat(champion_stats, "level"))
        heal = _healing.extract_named(
            _healing.ability_json(champion_data, "W"), "Heal", level, champion_stats, {}
        )
        for event in _healing.attributed_events(
            damage_events, lambda source, _event: source == "auto_attacks"
        ):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": _healing.missing_health_scaled_heal(0.0, heal),
                    "source": "Hunter's Vigor",
                    "kind": "champion_passive",
                    **_healing.trigger_fields(event),
                }
            )
            break
    return healing


SELF_HEALING_RULE = self_healing_rule("Kindred")(derive_self_healing)
