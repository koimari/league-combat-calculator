"""Tahm Kench's acquired-taste and defensive-state packets.

E (Thick Skin) stays off the slot map — it damages nothing, and a slot
would invent a cast — so the contract derives ``out_of_scope`` for it.
The mechanic itself is priced elsewhere: the shared grey-health
primitive (``participant_timeline._grey_health_receipts``, reached
through ``healing.GREY_HEALTH_RULE_CHAMPIONS``) reads E's rank off the
skill order and works the incoming ledger. Runtime probe, level 18 / E
rank 5 / one enemy dealing 314.4 post-mitigation: ``grey_health_stored``
147.75 (0.47 x, the rank row) and a ``Thick Skin (grey health)`` heal of
147.75 four seconds after the last hit — which lands only when the fight
leaves him those four seconds, exactly as the wiki states. The E ACTIVE
(grey health converted into a 2.5 s shield) is the part with no channel:
the pool is walk state and a parse-time ``attach_self_shield`` payload
cannot read it.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .healing_contract import declare_healing_rule
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    simple_damage,
)
from .source_receipts import load_champion_sources


def _acquired_taste(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if ability is None:
        return None
    bonus = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    entry = on_hit_entry("An Acquired Taste", bonus, "magic")
    entry["detail"] = "basic attacks and Tongue Lash apply one stack"
    return entry


_acquired_taste.phase = ONHIT


def _tongue_lash(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    # Tongue Lash's row carries a per-rank base and an eighteen-entry per-level
    # term, so reading it needs the level as well as the rank.
    total = extract_named(
        ability, "Magic Damage", rank, ctx.stats, ctx.target, level=ctx.level
    )
    stacks = min(max(int(ctx.option("q_passive_stacks")), 0), 3)
    if stacks:
        total += extract_named(
            ctx.ability("P") or ability,
            "Per-Level Scaling",
            ctx.level,
            ctx.stats,
            ctx.target,
        )
    entry = damage_entry(
        ability.get("name", "Tongue Lash"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    # Q's crowd control is stack-dependent, so it is authored on the part
    # rather than declared once in MODULE_CC: the lash "deals magic damage
    # to the first enemy hit and slows them by 50% for 2 seconds", and the
    # "An Acquired Taste Bonus" at three stacks adds "The target is
    # stunned for 1.5 seconds" on top of it.
    entry["parts"] = (
        DamagePart(
            "magic",
            total,
            time_offset=0.0,
            cc_kind="stun" if stacks >= 3 else "slow",
        ),
    )
    entry["detail"] = f"{stacks} Acquired Taste stack(s) before Q"
    return entry


def _regurgitate(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R", 1)
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Regurgitate"),
        rank,
        extract_cooldown(ctx.ability("R") or ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.4),)
    entry["detail"] = "enemy Regurgitate target"
    return entry


SLOTS = {
    "P": _acquired_taste,
    "Q": _tongue_lash,
    # One emergence, one blow ("dealing magic damage to nearby enemies and
    # knocking them up and stunning them for 1 second").
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    # Thick Skin is grey-health/shield state, not damage; omitting it keeps
    # the damage timeline from inventing an enemy hit.  The E8a grey-health
    # primitive authors the E store (15/23/31/39/47% by rank, 42-50% with
    # 2+ visible enemies) and the out-of-combat restore heal from the
    # incoming ledger; the E active (grey -> 2.5 s shield) stays out of
    # the heal primitive's scope.
    "R": _regurgitate,
}

# Reviewed crowd control, read from the cached kit.  W (Abyssal Dive)
# lands "dealing magic damage to nearby enemies and knocking them up and
# stunning them for 1 second" — two immobilize kinds on one target, so the
# reviewed answer is the un-narrowed one.  R prices Regurgitate, the spit
# at the end of Devour, and Devour "can only be cast on enemies with 3
# stacks of An Acquired Taste", whose bonus reads "The target is
# suppressed during Devour's cast time and while attached".  P is an
# on-hit rider on the attack stream and Q's answer is stack-dependent, so
# Q authors its own kind on its part.
MODULE_CC = {"W": "immobilize", "R": "suppression"}

parse_abilities = build_parser(SLOTS, "Tahm Kench", cc_kinds=MODULE_CC)

OPTIONS = [
    {
        "key": "q_passive_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 3,
        "label": "Acquired Taste stacks before Q",
    }
]

ASSUMPTIONS = [
    "An Acquired Taste is an explicit on-hit rider; Q may opt into the bonus damage from a pre-existing stack state.",
    "Thick Skin stores 15/23/31/39/47% of post-mitigation damage taken as "
    "grey health (42/44/46/48/50% with 2+ visible enemies); the "
    "out-of-combat consume (4 s without damage) restores 60% : 100% "
    "based on level of the pool as a heal — the E8a grey-health "
    "primitive authors it from the incoming ledger. The E active "
    "converts grey into a 2.5 s shield and is defensive state, not a heal.",
    "R defaults to the enemy Regurgitate branch; ally Devour is a separate support/shield scenario.",
]

SOURCES = load_champion_sources("Tahm Kench")


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Tahm Kench self-healing events from its authored packet."""
    healing = []
    q = _healing._ability(champion_data, "Q")
    q_rank = _healing._rank(ability_damages, "Q")
    q_flat = _healing.extract_named(q, "Heal", q_rank, champion_stats, {})
    q_missing_pct = _healing._leveling_modifier(q, "Heal", q_rank, 1)

    def tongue_lash_heal(
        current_health: float,
        maximum_health: float,
        flat: float = q_flat,
        missing_pct: float = q_missing_pct,
    ) -> float:
        return flat + max(0.0, maximum_health - current_health) * missing_pct / 100.0

    for payment in _healing._payments(
        _healing.HealAnchor.CAST, "Q", damage_events, cast_timeline
    ):
        event = payment.event
        healing.append(
            {
                "time": float(event.get("time", 0.0)),
                "amount": 0.0,
                "amount_formula": tongue_lash_heal,
                "source": "Tongue Lash",
                "kind": "champion_ability",
                **_healing._trigger_fields(event),
            }
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Tahm Kench", derive_self_healing)
