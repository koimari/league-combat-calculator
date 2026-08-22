"""Small, typed helpers shared by named champion modules.

The helpers deliberately accept the cached ability JSON instead of carrying a
second table of values.  That keeps rank, level, resource and cooldown values
on the revision-pinned Wiki packet and makes a missing source field fail
closed in the same place as the other reviewed modules.  This module owns no
champion membership or champion-specific formulas.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, SlotParser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)

REVIEWED_MODULE_ASSUMPTIONS = (
    "Every passive/Q/W/E/R slot was reviewed against the complete parent Wiki "
    "entry and its five namespace-10 template receipts.",
    "Only the explicit one-rotation target/variant options are priced; utility, "
    "control, movement, healing and defensive state remain named rather than "
    "guessed.",
    "All numeric rank/level values are read from the cached source JSON through typed extractors.",
)


def typed_damage(
    ctx: SlotCtx,
    attribute: str,
    damage_type: str,
    *,
    count: int = 1,
    time_offset: float | None = None,
    hit_interval: float | None = None,
    rank_override: int | None = None,
    source_slot: str | None = None,
) -> dict[str, Any] | None:
    """Build one explicitly named typed packet from cached champion data."""

    slot = source_slot or ctx.slot
    ability = ctx.ability(slot)
    if ability is None:
        return None
    selected = rank_override if rank_override is not None else ctx.rank_for(slot)
    if slot == "P" and rank_override is None:
        selected = ctx.level
    if selected < 1:
        return None
    value = extract_named(ability, attribute, selected, ctx.stats, ctx.target)
    entry = damage_entry(
        str(ability.get("name", slot)),
        selected,
        extract_cooldown(ability, selected),
        value * max(1, count),
        damage_type,
    )
    entry["parts"] = (
        DamagePart(
            damage_type,
            value,
            count=max(1, count),
            time_offset=time_offset,
            hit_interval=hit_interval,
        ),
    )
    return entry


def delayed_damage(*, delay: float, **simple_damage_kwargs: Any) -> SlotParser:
    """A :func:`slotlib.simple_damage` slot whose hit lands after a delay.

    ``DamagePart.time_offset`` is seconds from the cast start, so an ability
    the cache places on a post-cast delay authors that number here rather
    than certifying a cast-boundary hit it does not have.  Where the cached
    entry says the delay excludes the cast time, the caller adds the cached
    ``castTime`` and passes the sum, because the champion module is what
    knows its source's convention.  Every ``simple_damage`` keyword passes
    through unchanged, so the delayed slot and the plain one price alike.
    """
    base = simple_damage(**simple_damage_kwargs)

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = base(ctx)
        if entry is None:
            return None
        entry["parts"] = tuple(
            replace(part, time_offset=delay) for part in entry.get("parts", ())
        )
        return entry

    parse.phase = base.phase
    return parse


def mixed_damage(
    _ctx: SlotCtx,
    name: str,
    rank_value: int,
    cooldown: float,
    magic: float,
    true_damage: float,
    *,
    detail: str,
) -> dict[str, Any]:
    """Build an explicitly split magic/true damage receipt."""

    parts = (DamagePart("magic", magic), DamagePart("true", true_damage))
    return {
        "name": name,
        "rank": rank_value,
        "cooldown": cooldown,
        "damage_type": "mixed",
        "total_raw": magic + true_damage,
        "parts": parts,
        "detail": detail,
    }


def rank(ctx: SlotCtx) -> int:
    """Return the selected skill rank, or zero when the slot is unlearned."""

    return ctx.rank_for() if ctx.slot != "P" else ctx.level


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp *value* into ``[lower, upper]``."""

    return min(upper, max(lower, value))


def missing_hp_fraction(ctx: SlotCtx) -> float:
    """The shared ``target_missing_hp_pct`` option as a 0..1 fraction."""

    return clamp(float(ctx.option("target_missing_hp_pct")), 0.0, 100.0) / 100.0


def buff_window_share(ctx: SlotCtx, duration: float) -> float:
    """Share of the fight window a self-buff lasting *duration* covers.

    ``fight_duration_seconds`` is zero in one-rotation mode and in a direct
    parse call, so with no window the whole bonus lands."""

    window = float(ctx.option("fight_duration_seconds"))
    if window <= duration:
        return 1.0
    return duration / window


def no_damage(
    ctx: SlotCtx,
    *,
    name: str,
    reason: str,
    slot: str | None = None,
    cooldown: float | None = None,
) -> dict[str, Any] | None:
    """Emit an explicit, user-visible state/utility row."""

    ability = ctx.ability(slot or ctx.slot)
    if ability is None:
        return None
    selected_rank = ctx.rank_for(slot or ctx.slot)
    if (slot or ctx.slot) == "P":
        selected_rank = ctx.level
    if selected_rank < 1:
        return None
    entry: dict[str, Any] = {
        "name": name,
        "rank": selected_rank,
        "cooldown": (
            float(cooldown)
            if cooldown is not None
            else extract_cooldown(ability, selected_rank)
        ),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": reason,
    }
    return entry


def no_damage_parser(
    slot: str, reason: str = "No enemy damage is listed for this ability."
):
    """Build a slot parser emitting an explicit zero-damage entry.

    Unlike ``no_damage`` this is not rank-gated and carries no cooldown: a
    state/utility slot keeps its named row even at rank 0 so the reason stays
    user-visible.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


def rank_gated_no_damage_parser(
    slot: str, reason: str = "No enemy damage is listed for this ability."
):
    """A :func:`no_damage_parser` row that is ABSENT while unlearned.

    The engine rotates every slot at every rank, so a heal/cleanse-only
    ultimate (Milio R, Olaf R) would otherwise book a cast at rank 0 and
    let its heal rule fire off the clamped last row.
    """
    inner = no_damage_parser(slot, reason=reason)

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        if ctx.rank_for() < 1:
            return None
        return inner(ctx)

    parse.phase = "damage"
    return parse


# P4: the shared Yasuo/Yone crit-conversion rule.  The cached P prose is
# verbatim Yasuo's for both ("total critical strike chance is doubled ...
# every 1% ... converted into 0.5 bonus attack damage ... 90% of the
# critical damage champions usually have"); both champions carry the
# champion stat criticalStrikeDamageModifier.flat = 0.9; the binaries
# corroborate CritDamageMod 0.9 + CritToAD 50.0 (the x2 chance is
# script-side).  The Q's degraded "Critical Strike Damage" rows (189% +
# 28.35% AD = 1.05 x 1.8 + 1.05 x 0.27; 198% + 29.7% AD = 1.1 x 1.8 +
# 1.1 x 0.27) are the display of this same converted system.
CRIT_CHANCE_MULTIPLIER = 2.0
CRIT_DAMAGE_MULTIPLIER_FACTOR = 0.9
EXCESS_CRIT_BONUS_AD_PER_PERCENT = 0.5


def crit_conversion_payload() -> dict[str, Any]:
    """The engine's crit_modifier payload for the shared conversion."""
    return {
        "crit_chance_multiplier": CRIT_CHANCE_MULTIPLIER,
        "crit_damage_multiplier_factor": CRIT_DAMAGE_MULTIPLIER_FACTOR,
        "excess_crit_bonus_ad_per_percent": EXCESS_CRIT_BONUS_AD_PER_PERCENT,
    }


def crit_conversion_certification(
    atom_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(certified_constants, atom_ids) for the conversion rule.

    The 0.9 factor is the champion stat criticalStrikeDamageModifier.flat
    (the pinned atom hash varies per champion); the x2 chance + 0.5 AD
    per excess % are cached-P-prose + binary roots.  A patch that
    changes the roots trips the pinned hash (fail-closed staleness).
    """
    cert = dict(crit_conversion_payload())
    atoms = {
        "crit_damage_multiplier_factor": {
            "atom_id": "stats.critical_strike_damage_modifier.flat",
            "hash": atom_hash,
        },
    }
    return cert, atoms
