"""Aatrox — slot map for the archetype engine.

Why each slot is non-generic:
- R (World Ender) grants bonus AD as a PERCENTAGE of total AD — a
  ``stat_buff`` in percent_of mode (BUFF phase, so Q/W scale off the
  buffed AD).
- Q (The Darkin Blade) is three sequential casts with individually
  named damage attributes; ``_darkin_blade`` emits one part per strike,
  spaced by the cached 1-second static recast cooldown.
- W (Infernal Chains) hits twice — the chain's "Physical Damage" on
  impact and the same amount again when the cached 1.5-second tether
  expires; the two sum to the cached "Total Damage" attribute exactly.
- P (Deathbringer Stance) is on-hit magic damage as a per-LEVEL
  percentage of target max health — champion-local ``_deathbringer_stance``.
- E (Umbral Dash) is a dash with healing amp only — no enemy damage of
  its own, so ``_umbral_dash`` emits a sourced zero rather than leaving
  the slot absent. It is still ``modeled``: ``derive_self_healing``
  prices its heal share of every damaging hit, the
  ``self_healing_rule`` channel the coverage map names. Only the dash
  itself — mobility, an axis the engine lacks — is unpriced.

All numeric values are read from the champion JSON data; nothing is
hardcoded.

Roadmap session (2026-08-21): closes the single out_of_scope slot (E).
E (Umbral Dash): ``data/champions.json`` Aatrox E carries
``damageType: None`` and its three effect rows are entirely non-combat
text — "Passive: Aatrox heals for 16% (+ 1.1% per 100 bonus health) of
non-persistent post-mitigation damage he deals against enemy champions"
(the heal, already modeled by ``derive_self_healing``'s E-ratio path),
"Active: Aatrox dashes in the target direction" (a pure position change),
and the basic-attack-timer-reset/cast-interrupt clause (mobility/utility,
not a combat number). No effect row carries a ``leveling`` entry at all —
there is no enemy-damage attribute anywhere on this ability to model.
So the slot emits an atoms-confirmed zero-HP-number row rather than
staying silently absent, and its heal keeps it ``modeled`` through the
``self_healing_rule`` channel.
"""

import re
from collections.abc import Iterable
from typing import Any

from ..ability_atoms import ability_field, ability_payload
from ..ability_spec import DamagePart
from ..healing_helpers import (
    HealAnchor,
    ability_json,
    event_source,
    leveling_value,
    payments,
    trigger_fields,
)
from .engine import ONHIT, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import champion_stat, int_option
from .module_helpers import no_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_description_duration,
    extract_named,
    on_hit_entry,
    pct_health_per_hit,
    stat_buff,
)
from .source_receipts import load_champion_sources

_Q_SWEETSPOT_ATTRS = [
    "First Sweetspot Damage",
    "Second Sweetspot Damage",
    "Third Sweetspot Damage",
]
_Q_NORMAL_ATTRS = [
    "First Cast Damage",
    "Second Cast Damage",
    "Third Cast Damage",
]
_Q_VARIANT_ATTRS = [
    *_Q_NORMAL_ATTRS[:1],
    *_Q_SWEETSPOT_ATTRS[:1],
    *_Q_NORMAL_ATTRS[1:2],
    *_Q_SWEETSPOT_ATTRS[1:2],
    *_Q_NORMAL_ATTRS[2:3],
    *_Q_SWEETSPOT_ATTRS[2:3],
    "Maximum Non-Minion Non-Sweetspot Damage",
    "Maximum Non-Minion Sweetspot Damage",
]

# The Darkin Blade's three strikes are one second apart: "Aatrox can
# activate The Darkin Blade three times before the ability goes on
# cooldown, with a 1-second static cooldown between casts" (data/
# champions.json Aatrox Q), and the cache names each strike's damage on its
# own row, so the triad lands at 0, 1 and 2 seconds from the first.  The
# hyphenated "1-second" is why this is a module constant rather than a
# ``extract_description_duration`` read: that reader wants "1 second", and
# the next seconds value in the same sentence is the 4-second recast window.
# ``tests/test_aatrox.py`` pins the constant against the cached sentence.
_Q_STRIKE_INTERVAL_SECONDS = 1.0

# Which of the three strikes each single-strike attribute prices.  The two
# "Maximum Non-Minion …" rows are the triad's own sum (per rank, and
# exactly: 37.5 = 10 + 12.5 + 15, 225% AD = 60 + 75 + 90% AD, and the same
# for the Sweetspot pair), so they are priced from their three components
# instead — one aggregate row cannot carry three landing times.
_Q_STRIKE_ORDINAL = {
    "First Cast Damage": 0,
    "First Sweetspot Damage": 0,
    "Second Cast Damage": 1,
    "Second Sweetspot Damage": 1,
    "Third Cast Damage": 2,
    "Third Sweetspot Damage": 2,
}
_Q_TRIAD_COMPONENTS = {
    "Maximum Non-Minion Non-Sweetspot Damage": _Q_NORMAL_ATTRS,
    "Maximum Non-Minion Sweetspot Damage": _Q_SWEETSPOT_ATTRS,
}


def _q_strike_parts(
    ctx: SlotCtx, ability: dict[str, Any], rank: int, attrs: Iterable[str]
) -> tuple[DamagePart, ...]:
    """One part per named strike, at the strike's sourced landing time."""
    return tuple(
        DamagePart(
            "physical",
            extract_named(ability, attr, rank, ctx.stats, ctx.target),
            time_offset=_Q_STRIKE_ORDINAL[attr] * _Q_STRIKE_INTERVAL_SECONDS,
        )
        for attr in attrs
    )


def _darkin_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the sweetspot or normal triad, one event per strike."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    detail = None
    if "q_variant" in ctx.options:
        try:
            variant = int(ctx.options["q_variant"])
        except (TypeError, ValueError):
            variant = len(_Q_VARIANT_ATTRS) - 1
        variant = max(0, min(variant, len(_Q_VARIANT_ATTRS) - 1))
        attribute = _Q_VARIANT_ATTRS[variant]
        attrs = _Q_TRIAD_COMPONENTS.get(attribute, [attribute])
        detail = f"Q variant: {attribute}."
    else:
        # The declared default (variant 7) is the full sweetspot triad.
        attrs = _Q_SWEETSPOT_ATTRS

    parts = _q_strike_parts(ctx, ability, rank, attrs)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        sum(part.amount for part in parts),
        "physical",
    )
    entry["parts"] = parts
    if detail is not None:
        entry["detail"] = detail
    return entry


# Infernal Chains' tether effect is the cached effect row that times the
# second hit: "a tether is formed between the target and the ground beneath
# them for 1.5 seconds", and the row after it says that at the tether's end
# "the target is dealt the same physical damage again".
_W_TETHER_EFFECT_INDEX = 1
_W_HITS = 2


def _infernal_chains(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the chain hit, then the same damage again when the tether expires.

    The cached "Total Damage" row is exactly twice "Physical Damage" at
    every rank, so pricing the two hits separately keeps the total and buys
    the tether's cached delay.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    tether_seconds = extract_description_duration(ability, _W_TETHER_EFFECT_INDEX)
    if tether_seconds is None:
        raise ValueError(
            "Aatrox W: the cached Infernal Chains effect "
            f"{_W_TETHER_EFFECT_INDEX} states no tether duration, so the "
            "pull-back hit has no sourced time"
        )
    per_hit = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_hit * _W_HITS,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            per_hit,
            count=_W_HITS,
            time_offset=0.0,
            hit_interval=tether_seconds,
        ),
    )
    return entry


def _deathbringer_stance(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: per-level target-max-health on-hit damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_hit = pct_health_per_hit(
        ability,
        "Max Health Damage",
        ctx.level,
        ctx.target,
    )
    if per_hit is None:
        return None
    return on_hit_entry(ability_name(ability), per_hit, "magic")


_deathbringer_stance.phase = ONHIT


def _umbral_dash(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: dash + heal-amp utility — sourced zero-enemy-damage row (no_damage).

    The cached E entry carries ``damageType: None`` and no effect row has a
    ``leveling`` attribute; the passive heal (16% + 1.1% per 100 bonus
    health of non-persistent post-mitigation damage dealt) is already
    priced through ``derive_self_healing`` and the active dash is a pure
    position change. Nothing here deals damage to an enemy champion.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            "Umbral Dash is a self-heal-amp dash with no enemy-damage "
            "attribute of its own (data/champions.json Aatrox E carries "
            "damageType: None and no effect row has a leveling entry); "
            "its heal is priced through derive_self_healing."
        ),
    )


OPTIONS = [
    int_option(
        "q_variant",
        7,
        minimum=0,
        maximum=7,
        label="Q damage variant",
    ),
]

ASSUMPTIONS = [
    "Assumed R is always active",
    "W always hits both initial and pull-back damage: the tether is never "
    "broken, so the second hit lands 1.5 cached seconds after the first",
    "Q always lands all three strikes, one second apart",
    "E (Umbral Dash) carries no enemy-damage attribute (damageType: None, "
    "no leveling row on any effect); it emits a sourced no_damage row. Its "
    "heal is priced through derive_self_healing, not this slot.",
]

SLOTS = {
    "R": stat_buff(
        "Bonus Attack Damage",
        "bonus_attack_damage",
        mode="percent_of",
        percent_of="attack_damage",
        apply_to=("attack_damage", "bonus_attack_damage"),
    ),
    "Q": _darkin_blade,
    "W": _infernal_chains,
    "P": _deathbringer_stance,
    "E": _umbral_dash,
}

# MODULE_CC is empty because neither cast controls unconditionally, not
# because a cadence is missing: both slots now author their sourced landing
# times above, so a kind declared here would reach the ledger.
#
# Q (The Darkin Blade) knocks up only "enemies hit within a Sweetspot of the
# area" — the sweetspot rows of this module's ``q_variant`` option — so the
# knockup belongs to a branch of the slot rather than to the slot, and
# ``MODULE_CC`` is a per-slot map.
#
# W (Infernal Chains) applies two different kinds: the chain hit slows
# ("slowing them for 1.5 seconds") and the tether hit pulls ("the target is
# dealt the same physical damage again and pulled to the center of the
# area").  ``MODULE_CC`` carries one kind per slot, so declaring either
# would state the other as well.
#
# R fears "nearby enemy minions and monsters" only and authors no damage
# part; P is the on-hit stance row.
MODULE_CC: dict[str, str] = {}

parse_abilities = build_parser(SLOTS, "Aatrox", cc_kinds=MODULE_CC)


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
def _is_persistent(event: dict[str, Any]) -> bool:
    """Return the source-certified persistent/periodic damage boundary.

    The engine's own source keys are stable public receipts for these rows;
    no damage amount or champion archetype is guessed here.
    """
    source = event_source(event).lower()
    return (
        source.startswith(("burn_", "stacking_dot_", "immolate_"))
        or "tibbers_aura" in source
    )


def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Price Deathbringer Stance and Umbral Dash healing for Aatrox."""
    del cast_timeline, fight_duration_seconds
    healing: list[dict[str, Any]] = []
    # Both rules pay a share of what a hit dealt — Deathbringer Stance
    # "heals for a percentage of the damage dealt" and Umbral Dash the same
    # for every damage source — so both pay per hit that dealt some.
    passive_payments = payments(
        HealAnchor.DAMAGING_HIT,
        lambda source: "passive" in source.lower(),
        damage_events,
    )
    e_description = " ".join(
        effect.get("description", "")
        for effect in ability_json(champion_data, "E").get("effects", [])
    )
    ratio_match = re.search(
        r"heals for\s+(\d+(?:\.\d+)?)%\s*\(\+\s*(\d+(?:\.\d+)?)%\s*per\s*100\s*bonus health",
        e_description,
        flags=re.IGNORECASE,
    )
    base_ratio = float(ratio_match.group(1)) / 100.0 if ratio_match else 0.0
    per_100 = float(ratio_match.group(2)) / 100.0 if ratio_match else 0.0
    e_ratio = base_ratio + per_100 * (
        float(champion_stat(champion_stats, "bonus_health")) / 100.0
    )
    r_rank = int(ability_field(ability_payload(ability_damages, "R"), "rank"))
    r_inc = leveling_value(
        ability_json(champion_data, "R"), "Increased Healing", r_rank
    )
    healing_amp = 1.0 + r_inc / 100.0 if r_rank > 0 else 1.0

    for payment in passive_payments:
        event = payment.event
        amount = max(0.0, float(event.get("damage", 0.0))) * healing_amp
        if amount > 0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": amount,
                    "source": "Deathbringer Stance",
                    "kind": "champion_passive",
                    **trigger_fields(event),
                }
            )

    for payment in payments(
        HealAnchor.DAMAGING_HIT, lambda _source: True, damage_events
    ):
        event = payment.event
        if _is_persistent(event):
            continue
        amount = max(0.0, float(event.get("damage", 0.0))) * e_ratio * healing_amp
        if amount > 0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": amount,
                    "source": "Umbral Dash",
                    "kind": "champion_passive",
                    **trigger_fields(event),
                }
            )
    return healing


SOURCES = load_champion_sources("Aatrox")

SELF_HEALING_RULE = self_healing_rule("Aatrox")(derive_self_healing)

# E's own row is a sourced zero, so SLOTS derives ``modeled`` without a
# damage number behind it; what prices the slot is the rule above, which
# pays Umbral Dash's heal off every damaging hit (821.5 over a level-18
# timed fight with autos).
COVERAGE_CHANNELS = {"E": ("self_healing_rule",)}
