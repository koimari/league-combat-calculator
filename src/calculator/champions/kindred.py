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

import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import champion_stat, int_option
from .module_helpers import no_damage, ranked_slot, typed_damage
from .shared_mechanics import capped_option
from .slot_control import park_control_interval
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)
from .source_receipts import load_champion_sources


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

# ROOTED IN THE BINARY (KindredEWrapper): how long Mounting Dread's mark
# stands, which every marked attack refreshes, and the slow the shot itself
# applies.  The sibling StacksToProc reads 4 against the cached prose's
# "stacking up to 3 times", because the binary counts the mark itself as
# the first stack; the module keeps the prose's three ATTACKS.
_E_MARK_SECONDS = data_value(
    spell_object("Kindred", "KindredEWrapper"), "TotalDuration"
)
_E_SLOW_SECONDS = data_value(spell_object("Kindred", "KindredEWrapper"), "SlowDuration")
_E_SLOW_PERCENT = data_value(spell_object("Kindred", "KindredEWrapper"), "SlowAmount")

_VIGOR_RE = re.compile(
    r"(?P<per_attack>\d+) stacks on-attack, up to a maximum of "
    r"(?P<maximum>\d+) stacks"
)


def _vigor_stack_terms(ability: dict[str, Any]) -> tuple[int, int]:
    """Hunter's Vigor's cached on-attack gain and its cap."""
    effects = ability.get("effects")
    for effect in effects if effects else ():
        description = effect.get("description")
        if description is None:
            continue
        match = _VIGOR_RE.search(str(description))
        if match is not None:
            return int(match.group("per_attack")), int(match.group("maximum"))
    raise ValueError(
        "Kindred W: the cached passive no longer states Hunter's Vigor's "
        "on-attack gain and cap ('N stacks on-attack, up to a maximum of N "
        "stacks')"
    )


def _vigor_attacks_to_fill(ability: dict[str, Any]) -> int:
    """How many of Lamb's attacks fill the bar, counting nothing else."""
    # Movement fills it too, at one stack per 27 units, and this engine has
    # no movement to walk. Counting only the attacks can delay a heal and
    # can never invent one.
    per_attack, maximum = _vigor_stack_terms(ability)
    return -(-maximum // per_attack)


# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Mounting Dread's third-stack pounce "increased by 0% : 50% (+ 0% :
# 15%) (based on critical strike chance)" (the Akshan-R / Caitlyn-R
# crit_effectiveness precedent).
# ROOTED IN THE BINARY (KindredEWrapper.CritMod); the wiki prose
# ("+ 0% : 15% (based on critical strike chance)") corroborates the
# crit_effectiveness semantics (the Akshan-R / Caitlyn-R precedent).
_E_POUNCE_CRIT_EFFECTIVENESS = data_value(
    spell_object("Kindred", "KindredEWrapper"), "CritMod"
)


def _marks(ctx: SlotCtx) -> int:
    return capped_option(ctx, "marks", _MARK_MAX)


def _mark_scaled_override(
    ctx: SlotCtx, marks: int, unit_phrase: str, per_mark: float, *, target_stat: str
):
    """A modifier override: the unit naming *unit_phrase* grows *per_mark* per Mark."""

    def override(unit: str, value: float) -> float | None:
        if unit_phrase not in unit:
            return None
        percent = value + per_mark * marks
        return percent / 100.0 * float(ctx.target_stat(target_stat) or 0.0)

    return override


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


def _pounce_damage(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> float | None:
    """The sourced pounce packet, or ``None`` when its row is missing."""
    leveling = find_named_leveling(ability, "Additional Physical Damage")
    if leveling is None:
        return None
    # E's missing-health modifier: 5% (+ 0.5% per Mark).
    return sum_modifiers(
        leveling,
        rank,
        ctx.stats,
        ctx.target,
        modifier_override=_mark_scaled_override(
            ctx,
            _marks(ctx),
            "of target's missing health",
            0.5,
            target_stat="target_missing_health",
        ),
    )


def _pounce_part(damage: float) -> DamagePart:
    """The pounce's one part, crit-scaled by the binary's CritMod."""
    return DamagePart(
        "physical",
        damage,
        crit_effectiveness=_E_POUNCE_CRIT_EFFECTIVENESS,
    )


@ranked_slot
def _mounting_dread(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: Mounting Dread — the shot, and the pounce a STATED level prices.

    Unset, the shot only marks and slows: the pounce is its own row
    (``E_pounce``), because it lands on the third marked attack rather than
    at the cast. The slow then has no damage event to ride, so the row parks
    it as a typed control interval (Veigar E's cage precedent), which the
    rotation replays per cast whatever the row prices.
    """
    requested = ctx.options.get("e_stacks")
    if requested is None:
        entry = no_damage(
            ctx,
            name=ability_name(ability),
            reason=(
                f"The shot slows by {_E_SLOW_PERCENT:g}% for "
                f"{_E_SLOW_SECONDS:g}s and marks the target for "
                f"{_E_MARK_SECONDS:g}s; every marked basic attack applies a "
                "stack and refreshes it, and the third directs Wolf to "
                "pounce, which E_pounce prices at the attack that lands it."
            ),
        )
        if entry is not None:
            park_control_interval(
                entry, _E_SLOW_SECONDS, magnitude=_E_SLOW_PERCENT / 100.0
            )
        return entry
    stacks = min(max(int(requested), 1), _E_STACK_MAX)
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

    damage = _pounce_damage(ctx, ability, rank)
    if damage is None:
        return None
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    entry["parts"] = (_pounce_part(damage),)
    entry["target_max_health_sensitive"] = True
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"Third-stack Wolf pounce at {stacks}/3 stacks: {damage:.2f} "
        "physical (80 : 200 by rank + 100% bonus AD + 5% (+0.5% per "
        f"Mark) of missing health at {_marks(ctx)} mark(s)); the pounce "
        "consumes all stacks."
    )
    return entry


def _wolf_pounce(ctx: SlotCtx) -> dict[str, Any] | None:
    """E_pounce: the pounce itself, on the attack that completes the count.

    Only the DERIVED reading emits it. A stated level prices the pounce at
    the cast, on the E row, which is where it has always been.  The row
    reads E's own ability and rank: it is E's damage, landing later.
    """
    if ctx.options.get("e_stacks") is not None:
        return None
    ranked = ctx.ranked("E")
    if ranked is None:
        return None
    ability, rank = ranked
    damage = _pounce_damage(ctx, ability, rank)
    if damage is None:
        return None
    entry = damage_entry(
        "Mounting Dread (Wolf pounce)",
        rank,
        0.0,
        damage,
        "physical",
    )
    entry["parts"] = (_pounce_part(damage),)
    entry["target_max_health_sensitive"] = True
    entry["proc_count"] = 1
    # "Her basic attacks against the marked target each apply a stack,
    # refreshing the duration and stacking up to 3 times. The third stack
    # directs Wolf to pounce, consuming all stacks." The cast marks and the
    # attacks count, so the fight walks how many pounces the marks afford
    # and a fight that lands no third marked attack affords none.
    entry["armed_procs"] = {
        "arming_slots": ("E",),
        "max_stacks": _E_STACK_MAX,
        "hits_required": _E_STACK_MAX,
        "stacks_from_swings": True,
        "stack_seconds": _E_MARK_SECONDS,
        "armed_at_start": False,
        "requested": False,
    }
    entry["detail"] = (
        f"{damage:.2f} physical on the third marked attack (80 : 200 by rank "
        f"+ 100% bonus AD + 5% (+0.5% per Mark) of missing health at "
        f"{_marks(ctx)} mark(s)), consuming all stacks; the mark stands "
        f"{_E_MARK_SECONDS:g}s and every marked attack refreshes it."
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
    requested = ctx.options.get("w_hunters_vigor_stacks")
    per_attack, maximum = _vigor_stack_terms(ability)
    if requested is None:
        heal = extract_named(ability, "Heal", ctx.level, ctx.stats, ctx.target)
        attacks = _vigor_attacks_to_fill(ability)
        entry = no_damage(
            ctx,
            slot="W",
            name="Hunter's Vigor",
            reason=(
                f"{per_attack} stacks on-attack to a maximum of {maximum}, so "
                f"every {attacks} attacks fill the bar and the next one heals "
                f"Kindred for the missing-health share of {heal:g} (47 : 81 "
                "based on level); the fight walks the attacks that fill it. "
                "Movement fills it too, at one stack per 27 units, which this "
                "engine does not walk, so the count is a floor.  The heal is "
                "not triggered at full health."
            ),
        )
        if entry is not None:
            entry["heal_requires_stacks"] = {
                "per_hit": per_attack,
                "max_stacks": maximum,
                "attacks_to_fill": attacks,
                "repeats": True,
            }
        return entry
    stacks = min(max(int(requested), 0), maximum)
    if stacks < maximum:
        return no_damage(
            ctx,
            slot="W",
            name="Hunter's Vigor",
            reason=(
                f"{stacks}/{maximum} Hunter's Vigor stacks; at {maximum} the "
                "next basic attack heals Kindred for 0% : 100% (based on "
                "missing health) of 47 : 81 (based on level)."
            ),
        )
    heal = extract_named(ability, "Heal", ctx.level, ctx.stats, ctx.target)
    entry = no_damage(
        ctx,
        slot="W",
        name="Hunter's Vigor",
        reason=(
            f"{stacks}/{maximum} Hunter's Vigor stacks: the next basic attack "
            f"heals Kindred for the missing-health share of {heal:g} "
            "(47 : 81 based on level); the heal is not triggered at full "
            "health."
        ),
    )
    if entry is not None:
        # A bar stated full heals on the very next attack. The key is what
        # derive_self_healing reads, and a row below the cap carries none,
        # which is what stops a stated ZERO from healing: the row is emitted
        # either way, so its presence alone never meant the heal happened.
        # A stated level is a snapshot of one instant, not a bar the fight
        # keeps refilling, so it pays once the way it always has.
        entry["heal_requires_stacks"] = {
            "per_hit": per_attack,
            "max_stacks": maximum,
            "attacks_to_fill": 1,
            "repeats": False,
        }
    return entry


@ranked_slot
def _wolfs_frenzy(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: Wolf's Frenzy — Wolf basic attacks over the fight window.

    Wolf's attacks are magic and the rate scales with 25% of Kindred's
    bonus attack speed (wiki prose); the zone lasts 8.5 seconds.  The
    attack COUNT is the player-controlled ``w_attacks`` option (default
    3).  The per-Mark current-health term (1.5% + 1% per Mark) resolves
    through the same modifier override Mounting Dread uses, so the
    sourced formula prices exactly.
    """
    attacks = min(max(int(ctx.option("w_attacks")), 1), 8)
    marks = _marks(ctx)
    leveling = find_named_leveling(ability, "Magic Damage")
    if leveling is None:
        return None

    # Wolf's current-health modifier: 1.5% (+ 1% per Mark).
    per = sum_modifiers(
        leveling,
        rank,
        ctx.stats,
        ctx.target,
        modifier_override=_mark_scaled_override(
            ctx,
            marks,
            "of target's current health",
            1.0,
            target_stat="target_current_health",
        ),
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
    "E_pounce": _wolf_pounce,
    "R": _BASE_SLOTS["R"],
}

# Cached kit review: E's active "slows them by 30% (+ 5% per 100 AP) for 1
# second" on the target its pounce then damages; Q's arrows apply no
# control, and Wolf's frenzy attacks slow only "against monsters", never
# the champion this pair fight damages.  P, W_vigor and R deal no damage.
MODULE_CC = {"Q": "none", "W": "none", "E": "slow", "P": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Kindred", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option("marks", 0, minimum=0, maximum=25, label="Mark of the Kindred stacks"),
    int_option("w_attacks", 3, minimum=1, maximum=8, label="Wolf attacks (W)"),
    int_option(
        "w_hunters_vigor_stacks",
        100,
        minimum=0,
        maximum=100,
        label=(
            "Hunter's Vigor stacks (100 = the next basic attack heals); unset "
            "walks the attacks that fill the bar"
        ),
    ),
    int_option(
        "e_stacks",
        3,
        minimum=1,
        maximum=3,
        label=(
            "Mounting Dread stacks (3 = pounce); unset walks the marked "
            "attacks and pounces wherever the third one lands"
        ),
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
def _vigor_heal_events(
    counter: dict[str, Any] | None, damage_events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Which of Lamb's attacks carry the Hunter's Vigor heal."""
    if counter is None:
        return []
    every = int(counter["attacks_to_fill"])
    if every < 1:
        return []
    autos = list(
        _healing.attributed_events(
            damage_events, lambda source, _event: source == "auto_attacks"
        )
    )
    carried = [autos[index] for index in range(every - 1, len(autos), every)]
    return carried if counter["repeats"] else carried[:1]


def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Kindred self-healing events from its authored packet."""
    healing = []
    r = _healing.ability_json(champion_data, "R")
    r_rank = _healing.parsed_rank(ability_damages, "R")
    r_heal = extract_named(r, "Heal", r_rank, champion_stats)
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
        heal = extract_named(
            _healing.ability_json(champion_data, "W"), "Heal", level, champion_stats, {}
        )
        # A stated level at the cap says the bar is full right now, so the
        # first auto heals once. A derived one has to FILL it: the cached
        # gain and cap say how many attacks that takes, the healing attack
        # spends them, and the bar refills behind it. A stated level below
        # the cap carries no counter at all and heals nothing, which is the
        # reading the row's presence alone never gave.
        counter = ability_damages["W_vigor"].get("heal_requires_stacks")
        for event in _vigor_heal_events(counter, damage_events):
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

    return healing


SELF_HEALING_RULE = self_healing_rule("Kindred")(derive_self_healing)
