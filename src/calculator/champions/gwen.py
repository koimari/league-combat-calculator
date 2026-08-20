"""Gwen's max-health on-hit, center true conversion and R recasts."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, ONHIT, SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named


def _thousand_cuts(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    target_max = float(ctx.target_stat("target_max_health") or 0.0)
    # The parent page describes the champion branch as 1% (+0.6% per 100 AP)
    # of target maximum health. The level row in the cache is for the
    # minion-only rider and must not replace that formula.
    damage = target_max * (0.01 + 0.006 * ctx.stat("ability_power") / 100.0)
    if target_max <= 0.0:
        return no_damage(
            ctx,
            name="A Thousand Cuts",
            reason="Target maximum health is required before the max-health on-hit can be priced.",
            slot="P",
        )
    entry = no_damage(
        ctx,
        name="A Thousand Cuts",
        reason="Basic attacks carry Gwen's sourced max-health magic on-hit.",
        slot="P",
    )
    if entry is not None:
        entry["on_hit"] = {
            "name": "A Thousand Cuts",
            "damage_per_hit": damage,
            "damage_type": "magic",
        }
        entry["detail"] = (
            "1% + 0.6% per 100 AP of target maximum health per qualifying hit; champion heal is sustain."
        )
    return entry


_thousand_cuts.phase = ONHIT


# Snip Snip!'s snips are individually timed in the cached entry's notes:
# "The first snip happens at 0.13 seconds, the last one at the end of the
# cast time.  Bonus snips from Snippy stacks each happen at 0.45, 0.4,
# 0.35 and 0.23 seconds into the cast time."  The last snip's instant is
# the cached ``castTime``, read below rather than copied here.
_Q_FIRST_SNIP_SECONDS = 0.13
_Q_BONUS_SNIP_SECONDS = (0.23, 0.35, 0.4, 0.45)


def _snip_times(ability: dict[str, Any], bonus: int) -> tuple[float, ...]:
    """Every snip instant of one cast, first to last (the final snip last).

    ``bonus`` is how many Snippy snips the cast consumes, and each takes
    the next of the cached bonus instants; the final snip is the cast
    time itself, which is where the entry puts it.
    """
    try:
        final = float(str(ability.get("castTime", "")).strip())
    except ValueError as exc:
        raise ValueError(
            "Gwen Q: the cached castTime is no longer a plain number, so "
            "the final snip's sourced instant ('the last one at the end "
            "of the cast time') cannot be read"
        ) from exc
    return (
        (_Q_FIRST_SNIP_SECONDS,)
        + tuple(sorted(_Q_BONUS_SNIP_SECONDS[:bonus]))
        + (final,)
    )


def _snip_snip(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.option("q_snippy_stacks")), 0), 4)
    center = bool(ctx.options.get("q_center", True))
    # Gwen "snips at least twice", and "if Gwen has any Snippy stacks, she
    # consumes them to snip an additional time for each" — so the cached
    # Minimum rows are one plain snip plus the final one, and the Maximum
    # rows are five plus the final.  The reviewed reading prices a full
    # four-stack cast or none, so the bonus count is 4 or 0.
    bonus = 4 if stacks >= 4 else 0
    plain_attr = "Center Damage per Snip" if center else "Damage per Snip"
    final_attr = "Final Snip Center Damage" if center else "Final Snip Damage"
    plain = extract_named(ability, plain_attr, rank, ctx.stats, ctx.target)
    final = extract_named(ability, final_attr, rank, ctx.stats, ctx.target)
    times = _snip_times(ability, bonus)
    per_snip = tuple([plain] * (len(times) - 1) + [final])
    value = sum(per_snip)
    entry = damage_entry(
        ability.get("name", "Snip Snip!"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "mixed" if center else "magic",
    )
    parts: list[DamagePart] = []
    for time_offset, amount in zip(times, per_snip):
        if center:
            # "The center of each snip converts 50% of the damage to true
            # damage" — the magic half leads, as a mixed entry requires.
            parts.append(
                DamagePart(
                    "magic", amount * 0.5, time_offset=time_offset, cc_kind="none"
                )
            )
            parts.append(
                DamagePart(
                    "true", amount * 0.5, time_offset=time_offset, cc_kind="none"
                )
            )
        else:
            parts.append(
                DamagePart("magic", amount, time_offset=time_offset, cc_kind="none")
            )
    entry["parts"] = tuple(parts)
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"{stacks} Snippy stack(s), {'center' if center else 'outer'} hit; "
        f"{len(times)} snips at "
        f"{', '.join(f'{time:g}s' for time in times)}; "
        "center converts 50% to true damage."
    )
    return entry


def _hallowed_mist(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Hallowed Mist",
        reason="Mist untargetability and bonus resistances are defensive state; no outgoing damage.",
    )


_hallowed_mist.phase = BUFF


def _skip_n_slash(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    bonus = 15.0 + 0.20 * ctx.stat("ability_power")
    entry = damage_entry(
        ability.get("name", "Skip 'n Slash"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", bonus),)
    entry["empowers_next_auto"] = True
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "One empowered attack carries 15 + 20% AP bonus magic damage; attack speed/range are state."
    )
    return entry


def _needlework(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    casts = min(max(int(ctx.option("r_casts")), 1), 3)
    attrs = (
        "Damage with A Thousand Cuts",
        "Second Cast Total Damage",
        "Third Cast Total Damage",
    )
    parts: list[DamagePart] = []
    total = 0.0
    for index in range(casts):
        value = extract_named(ability, attrs[index], rank, ctx.stats, ctx.target)
        total += value
        parts.append(DamagePart("magic", value, time_offset=0.25 + index))
    entry = damage_entry(
        ability.get("name", "Needlework"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{casts} Needlework cast(s), with 1/3/5 needles and the sourced A Thousand Cuts rider."
    )
    return entry


SLOTS = {
    "P": _thousand_cuts,
    "Q": _snip_snip,
    "W": _hallowed_mist,
    "E": _skip_n_slash,
    "R": _needlework,
}
# E only empowers attacks.  R (Needlework) "deals magic damage to enemies
# hit and slows them for 1.5 seconds".  P and W author no damage part.
# Q (Snip Snip!) only cuts — its damage clauses carry no control word —
# and the cached entry times every snip of the cast, so the row now says
# so on hits the event ledger can see.
MODULE_CC = {"E": "none", "Q": "none", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Gwen", cc_kinds=MODULE_CC)

OPTIONS = [
    {
        "key": "q_snippy_stacks",
        "type": "int",
        "default": 4,
        "min": 0,
        "max": 4,
        "label": "Snippy stacks consumed by Q",
    },
    {"key": "q_center", "type": "bool", "default": True, "label": "Q center hit"},
    {
        "key": "r_casts",
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 3,
        "label": "Needlework casts",
    },
]

ASSUMPTIONS = [
    "A Thousand Cuts is an explicit max-health magic on-hit; its champion heal and minion/monster caps are not applied to champion TDD.",
    "Q exposes Snippy stack count and center true-damage conversion instead of treating the six-snip maximum as universal.",
    "R's first, second and third casts remain separate ordered events, each carrying the sourced passive rider.",
]

SOURCES = [
    source_row(
        "Gwen parent entry",
        "https://wiki.leagueoflegends.com/en-us/Gwen",
        4047585,
        "2026-07-29T22:50:16Z",
    ),
    source_row(
        "Gwen Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gwen/Q",
        3256220,
        "2021-03-30T16:42:34Z",
    ),
    source_row(
        "Gwen W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gwen/W",
        3256221,
        "2021-03-30T16:42:50Z",
    ),
    source_row(
        "Gwen E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gwen/E",
        3256222,
        "2021-03-30T16:43:07Z",
    ),
    source_row(
        "Gwen R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gwen/R",
        3256223,
        "2021-03-30T16:43:26Z",
    ),
]

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Gwen")
