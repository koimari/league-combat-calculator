"""Gwen's max-health on-hit, center true conversion and R recasts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, ONHIT, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat, float_option, int_option
from .module_helpers import no_damage
from .slotlib import ability_name, damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources

_GWEN_Q_SPELL = spell_object("Gwen", "GwenQ")
_GWEN_E_SPELL = spell_object("Gwen", "GwenE")
_Q_CENTER_TRUE_FRACTION = data_value(_GWEN_Q_SPELL, "TrueDamageConversion")
_E_BASE_DAMAGE = data_value(_GWEN_E_SPELL, "BaseDamage")


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
            "1% + 0.6% per 100 AP of target maximum health per qualifying hit; "
            "champion heal is sustain."
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


def _snip_times(ability: Mapping[str, Any], bonus: int) -> tuple[float, ...]:
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
    return (_Q_FIRST_SNIP_SECONDS, *tuple(sorted(_Q_BONUS_SNIP_SECONDS[:bonus])), final)


def _snip_snip(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    stacks = min(max(int(ctx.option("q_snippy_stacks")), 0), 4)
    center = bool(ctx.option("q_center"))
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
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "mixed" if center else "magic",
    )
    parts: list[DamagePart] = []
    for time_offset, amount in zip(times, per_snip, strict=False):
        if center:
            # "The center of each snip converts 50% of the damage to true
            # damage" — the magic half leads, as a mixed entry requires.
            parts.append(
                DamagePart(
                    "magic",
                    amount * (1.0 - _Q_CENTER_TRUE_FRACTION),
                    time_offset=time_offset,
                )
            )
            parts.append(
                DamagePart(
                    "true", amount * _Q_CENTER_TRUE_FRACTION, time_offset=time_offset
                )
            )
        else:
            parts.append(DamagePart("magic", amount, time_offset=time_offset))
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
        reason=(
            "Mist untargetability and bonus resistances are defensive state; no "
            "outgoing damage."
        ),
    )


_hallowed_mist.phase = BUFF


def _skip_n_slash(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    bonus = _E_BASE_DAMAGE + 0.20 * ctx.stat("ability_power")
    entry = damage_entry(
        ability_name(ability),
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
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
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
        ability_name(ability),
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
    int_option(
        "q_snippy_stacks", 4, minimum=0, maximum=4, label="Snippy stacks consumed by Q"
    ),
    bool_option("q_center", True, label="Q center hit"),
    int_option("r_casts", 3, minimum=1, maximum=3, label="Needlework casts"),
    bool_option(
        "w_active", False, label="W (Hallowed Mist) active against selected skillshots"
    ),
    float_option(
        "w_active_from",
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="W active start time in seconds",
    ),
    float_option(
        "w_active_seconds",
        0.0,
        minimum=0.0,
        maximum=4.0,
        label="W active seconds; zero uses the sourced four-second duration",
    ),
    {
        "key": "w_blocked_skillshots",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Skillshot slots to destroy; an empty list destroys all marked skillshots"
        ),
    },
]

ASSUMPTIONS = [
    "A Thousand Cuts is an explicit max-health magic on-hit; its champion "
    "heal and minion/monster caps are not applied to champion TDD.",
    "Q exposes Snippy stack count and center true-damage conversion instead "
    "of treating the six-snip maximum as universal.",
    "R's first, second and third casts remain separate ordered events, each "
    "carrying the sourced passive rider.",
    "Hallowed Mist destroys selected champion projectiles during its sourced "
    "four-second window; the single-target model exposes the source selection "
    "as the outside-mist contract.",
]

SOURCES = load_champion_sources("Gwen")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Gwen self-healing events from its authored packet."""
    healing = []
    p_level = int(champion_stat(champion_stats, "level"))
    per_instance_cap = extract_named(
        _healing.ability_json(champion_data, "P"),
        "Bonus Damage",
        p_level,
        champion_stats,
    )
    for event in _healing.attributed_events(
        damage_events,
        lambda source, _event: source == "on_hit_ability_passive",
    ):
        dealt = float(event.get("damage", 0.0))
        _healing.heal_from_damage(
            healing,
            event,
            min(0.50 * dealt, per_instance_cap),
            "A Thousand Cuts",
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Gwen")(derive_self_healing)
