"""Cho'Gath: slot map for the archetype engine.

E (Vorpal Spikes) empowers the next THREE basic attacks per cast, which the
generic parser reads as a single per-hit value with no hit count and no Feast
rider.  Each hit's "+ 0.5% per Feast stack" of the target's maximum health lives
only in the modifier's UNITS string, so a modifier override resolves it against
``feast_stacks``.  The pre-multiplied "Total Magic Damage" row and the two
Monster entries are never read.
R (Feast) couples true damage with the Feast-stack bonus health: each stack
grants bonus health retroactive to R's rank, and R's own %bonus-health ratio
must see that health, so R is a BUFF-phase function that mutates ``ctx.stats``
BEFORE extracting "Champion True Damage".  The "Non-Champion True Damage" row is
never read, and the buff is echoed in ``stat_buff`` for the fight engine.
Q (Rupture) and W (Feral Scream) are clean single-attribute reads of "Magic
damage" with a lowercase d; W's pick must never drift onto "Silence Duration".
P (Carnivore) heals on a kill, so its slot is a zero-damage receipt carrying the
declared kill count to the self-heal rule.  A duel simulates no wave, so the
count is ``p_carnivore_kills``, default 0, and the receipt is emitted only when
it is set.
"""

import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import ability_payload
from ..ability_spec import DamagePart
from ..damage_event_row import event_time as _row_time
from .engine import BUFF, SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import int_option
from .module_helpers import ability_slot, delayed_damage, ranked_slot
from .slot_control import with_control
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cast_time,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# E empowers the next 3 basic attacks per cast. The count has no JSON
# attribute of its own; the JSON's "Total Magic Damage" entry is exactly
# 3x the per-hit values (locked by tests/test_chogath.py).
SPIKES_ATTACKS_PER_CAST = 3

# E's Feast rider lives only in the %maxHP modifier's units text
# ("% (+ 0.5% per Feast stack) of target's maximum health"), so the
# per-stack percent is read out of the unit string and the number stays
# data-driven.  A %maxHP unit that stops stating the rider raises rather
# than falling through to the shared resolver, which would price the base
# percentage alone and understate every stack.
_MAX_HEALTH_UNIT = "maximum health"
_FEAST_STACK_RIDER = re.compile(
    r"\+\s*(\d+(?:\.\d+)?)%\s+per\s+Feast\s+stack", re.IGNORECASE
)

# Default Feast stacks: the minion / non-epic-monster stack cap.
_DEFAULT_FEAST_STACKS = 6

# Rupture erupts on its own delay: "Cho'Gath ruptures the target location
# after a 0.627 seconds delay ... dealing magic damage to enemies within
# and knocking them up for 1 second", with the cached note "The delay
# before the rupture does not include the cast time."  ``time_offset`` is
# measured from the cast start, so the cached castTime is added to the
# cached delay; both numbers come from the same Q entry.
_Q_RUPTURE_DELAY_S = 0.627


@ability_slot()
def _rupture(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """Q: the eruption, at the cached cast time plus the cached delay."""
    delay = extract_cast_time(ability) + _Q_RUPTURE_DELAY_S
    return delayed_damage(delay=delay, attr="Magic damage", dmg_type="magic")(ctx)


def _feast_stacks(ctx: SlotCtx) -> int:
    """Current Feast stacks: the option value, or 0 while R is unranked."""
    if ctx.rank_for("R") < 1:
        return 0
    return int(ctx.options.get("feast_stacks", _DEFAULT_FEAST_STACKS))


@ranked_slot
def _vorpal_spikes(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: 3 empowered attacks; per hit = base + 30% AP + %maxHP + rider.

    The empowered hits are real basic attacks: with an auto stream they
    ride it (item on-hits apply per hit — these ARE autos); with none
    (one-rotation, or timed at zero uptime) the cast forces its 3
    swings, which the fight engine appends via ``empowers_next_auto``'s
    ``hits`` count.
    """
    leveling = find_named_leveling(ability, "Magic Damage")
    if leveling is None:
        return None

    stacks = _feast_stacks(ctx)

    def _stack_rider(unit: str, value: float) -> float | None:
        if _MAX_HEALTH_UNIT not in unit:
            return None
        match = _FEAST_STACK_RIDER.search(unit)
        if match is None:
            raise ValueError(
                "Cho'Gath E (Vorpal Spikes): the cached %maxHP unit no longer "
                f"states its per-Feast-stack rider ({unit!r})"
            )
        percent = value + float(match.group(1)) * stacks
        return percent / 100.0 * ctx.target_stat("target_max_health")

    per_hit = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=_stack_rider
    )
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per_hit * SPIKES_ATTACKS_PER_CAST,
        "parts": (DamagePart("magic", per_hit, count=SPIKES_ATTACKS_PER_CAST),),
        "empowers_next_auto": {"hits": SPIKES_ATTACKS_PER_CAST},
    }


@ability_slot("P")
def _carnivore(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: the on-kill heal receipt the self-heal rule places.

    "Whenever Cho'Gath kills an enemy, it heals for 18 : 52 (based on
    level)" — a level row, not a rank one, and no damage of its own. The
    kills are player state the duel does not simulate, so the receipt only
    exists once the user declares some.
    """
    kills = max(0, int(ctx.option("p_carnivore_kills")))
    if kills <= 0:
        return None
    heal = extract_value(ability, "Heal", ctx.level, level=ctx.level)
    if heal <= 0.0:
        return None
    return {
        "name": ability_name(ability),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "self_heal_state": {"kills": kills, "amount": heal},
        "detail": (
            f"{kills} kill(s): {heal:g} health each (18 : 52 based on "
            "level); the mana restore has no champion-authored channel"
        ),
    }


@ranked_slot
def _feast(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """R (BUFF): stack bonus health first, then true damage off buffed stats.

    Unranked R emits nothing — without a rank there are no Feast stacks
    and no damage. The stack health mutates the shared parse stats
    (BUFF-phase guarantee) so R's own "% bonus health" ratio — and any
    other read of Cho'Gath's health — sees stacks plus item health.
    """

    stack_health = _feast_stacks(ctx) * extract_value(
        ability, "Bonus Health Per Stack", rank
    )
    ctx.stats["bonus_health"] = ctx.stat("bonus_health") + stack_health
    ctx.stats["health"] = ctx.stat("health") + stack_health

    total = extract_named(ability, "Champion True Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "true",
        # One bite on the target it eats, no travel or tick phase.
        event_order_certified="single_hit",
    )
    entry["stat_buff"] = {"bonus_health": stack_health}
    return entry


_feast.phase = BUFF


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "feast_stacks",
        _DEFAULT_FEAST_STACKS,
        minimum=0,
        maximum=15,
        label="Feast stacks",
        rotation={"role": "self_state", "slot": "R"},
    ),
    int_option(
        "p_carnivore_kills",
        0,
        minimum=0,
        maximum=10,
        label="Enemies Cho'Gath kills during the fight (P Carnivore)",
        step=1,
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": (
                "Carnivore pays on a kill, which no cast orders; the "
                "count is player state, not a rotation edge."
            ),
        },
    ),
]

ASSUMPTIONS = [
    "P (Carnivore) heals 18 to 52 by level per kill, the cached P Heal row, on the "
    "first damaging hits.",
    "A duel simulates no wave, so p_carnivore_kills (default 0) sets the count; the "
    "4.72 : 9.48 mana restore is not modeled.",
    "Feast stacks default to 6, the minion cap; champion and epic-monster stacks are "
    "uncapped, so raise the option.",
    "Feast bonus health is retroactive to the current R rank (stacks x 80/120/160); R "
    "unranked grants nothing.",
    "R uses the champion damage (300/475/650); the 1200 non-champion "
    "value is not modeled",
    "E models all 3 empowered attacks landing per cast; the monster "
    "damage variant is not modeled",
    "Q knockup and slow, W silence, E slow and reset, and Feast's size growth are "
    "utility and not modeled.",
]

SLOTS = {
    "P": _carnivore,
    "R": _feast,
    "Q": _rupture,
    # One roar in a cone, landing at the cast, carrying the sourced silence.
    "W": with_control(
        simple_damage(
            attr="Magic damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Silence Duration",
    ),
    "E": _vorpal_spikes,
}

# Cached kit review.  Q's rupture deals its magic damage while "knocking
# them up for 1 second" on the same delayed eruption, which the slot now
# authors; the 60% slow that follows rides the same airborne.  W's only
# debuff is a silence — real control, but neither an immobilizing effect
# nor a slow — and R "deal[s] them true damage" and nothing else.
#
# E's spikes ride the three basic attacks it empowers: "Enemies struck
# are dealt magic damage and slowed by an amount that decays over 1.5
# seconds" — one event per consumed swing, authored by the engine's
# empowered-swing reattribution.  P is a heal on a kill and touches no
# enemy at all.
MODULE_CC = {"P": "none", "Q": "knockup", "W": "silence", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Cho'Gath", cc_kinds=MODULE_CC)

# No MODULE_COVERAGE: every slot is in SLOTS and every slot prices a row
# the engine consumes — P's is the Carnivore heal the self-heal rule
# places — which is exactly what the contract derives.

SOURCES = load_champion_sources("Cho'Gath")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Price Carnivore: one heal per kill Cho'Gath's user declares.

    "Whenever Cho'Gath kills an enemy, it heals for 18 : 52 (based on
    level)" — P reads the level row and carries the user's declared kill
    count on its receipt.  A takedown-paid heal has neither a cast nor a
    damage row of its own, so each kill rides one of the fight's first
    damaging hits.
    """
    healing: list[dict[str, Any]] = []
    carnivore = ability_payload(ctx.ability_damages, "passive").get("self_heal_state")
    if isinstance(carnivore, dict):
        amount = float(carnivore.get("amount", 0.0) or 0.0)
        healing.extend(
            {
                "time": _row_time(payment.event),
                "amount": amount,
                "source": "Carnivore",
                "kind": "champion_passive",
                "actor_wide": True,
                **_healing.trigger_fields(payment.event),
            }
            for payment in _healing.takedown_payments(
                int(carnivore.get("kills", 0) or 0), ctx.damage_events
            )
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Cho'Gath")(derive_self_healing)
